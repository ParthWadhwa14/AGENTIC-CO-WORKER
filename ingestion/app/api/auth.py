from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from app.config import settings
from app.services.google_oauth import GoogleOAuthService
from app.storage.metadata_store import MetadataStore


router = APIRouter(prefix="/auth/google", tags=["google-auth"])


@router.get("/start")
def start_google_auth(
    user_id: str = Query(...),
    service: str = Query("workspace", pattern="^(workspace|drive|gmail)$"),
    login_hint: str | None = Query(None),
):
    try:
        url = GoogleOAuthService().authorization_url(
            user_id=user_id,
            service=service,
            login_hint=login_hint,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return RedirectResponse(url)


@router.get("/callback")
def google_auth_callback(request: Request, state: str = Query(...)):
    try:
        result = GoogleOAuthService().handle_callback(
            state=state,
            authorization_response=str(request.url),
        )
        params = urlencode(
            {
                "google_connected": result["provider"],
                "account_id": result["account_id"],
            }
        )
        return RedirectResponse(f"{settings.FRONTEND_URL}/?{params}")
    except Exception as exc:
        params = urlencode({"google_error": str(exc)})
        return RedirectResponse(f"{settings.FRONTEND_URL}/?{params}")


@router.get("/status")
def google_connection_status(user_id: str = Query(...)):
    return MetadataStore().connection_status(user_id)
