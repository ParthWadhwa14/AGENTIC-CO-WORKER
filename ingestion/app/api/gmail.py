from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from app.connectors.gmail_connector import GmailConnector
from app.services.tokens import GOOGLE_GMAIL_PROVIDER, GoogleCredentialStore
from app.storage.metadata_store import MetadataStore
from app.sync.gmail_sync import DEFAULT_GMAIL_QUERY, GmailSyncService


router = APIRouter(prefix="/gmail", tags=["gmail"])


def run_gmail_sync(
    user_id: str,
    mode: str,
    query: str,
    max_messages: int,
) -> None:
    service = GmailSyncService(user_id=user_id)
    if mode == "initial":
        service.initial_sync(query=query, max_messages=max_messages)
    elif mode == "partial":
        service.partial_sync()
    else:
        raise ValueError("mode must be 'initial' or 'partial'")


@router.get("/profile")
def gmail_profile(user_id: str = Query(...)):
    try:
        credentials = GoogleCredentialStore().get_credentials(
            user_id,
            provider=GOOGLE_GMAIL_PROVIDER,
        )
        profile = GmailConnector(credentials).get_profile()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return profile


@router.get("/labels")
def gmail_labels(user_id: str = Query(...)):
    try:
        credentials = GoogleCredentialStore().get_credentials(
            user_id,
            provider=GOOGLE_GMAIL_PROVIDER,
        )
        labels = GmailConnector(credentials).list_labels()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"user_id": user_id, "labels": labels}


@router.get("/messages")
def gmail_messages(
    user_id: str = Query(...),
    limit: int = Query(50, ge=1, le=500),
):
    messages = MetadataStore().list_gmail_messages(user_id=user_id, limit=limit)
    return {
        "user_id": user_id,
        "count": len(messages),
        "messages": messages,
    }


@router.post("/sync")
def sync_gmail(
    background_tasks: BackgroundTasks,
    user_id: str = Query(...),
    mode: str = Query("partial", pattern="^(initial|partial)$"),
    query: str = Query(DEFAULT_GMAIL_QUERY),
    max_messages: int = Query(100, ge=1, le=1000),
    background: bool = Query(True),
):
    if background:
        background_tasks.add_task(
            run_gmail_sync,
            user_id,
            mode,
            query,
            max_messages,
        )
        return {
            "user_id": user_id,
            "mode": mode,
            "status": "queued",
            "query": query,
            "max_messages": max_messages,
        }

    try:
        service = GmailSyncService(user_id=user_id)
        result = (
            service.initial_sync(query=query, max_messages=max_messages)
            if mode == "initial"
            else service.partial_sync()
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "user_id": user_id,
        "mode": mode,
        "status": "completed",
        "result": result,
    }
