import secrets
from urllib.parse import urlparse

from google_auth_oauthlib.flow import Flow

from app.config import settings
from app.services.google_client import load_google_client_config
from app.services.tokens import (
    GOOGLE_DRIVE_PROVIDER,
    GOOGLE_GMAIL_PROVIDER,
    GOOGLE_PROVIDER,
    GoogleCredentialStore,
)
from app.storage.metadata_store import MetadataStore


SERVICE_CONFIG = {
    "workspace": (GOOGLE_PROVIDER, settings.GOOGLE_READONLY_SCOPES),
    "drive": (GOOGLE_DRIVE_PROVIDER, settings.GOOGLE_READONLY_SCOPES),
    "gmail": (GOOGLE_GMAIL_PROVIDER, settings.GOOGLE_READONLY_SCOPES),
}


def _allow_local_http_oauth() -> None:
    if not settings.GOOGLE_REDIRECT_URI:
        return
    parsed = urlparse(settings.GOOGLE_REDIRECT_URI)
    if parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}:
        import os

        os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")


def _configured_authorization_response(authorization_response: str) -> str:
    if not settings.GOOGLE_REDIRECT_URI:
        raise ValueError("Set GOOGLE_REDIRECT_URI before starting Google OAuth.")

    configured = urlparse(settings.GOOGLE_REDIRECT_URI)
    actual = urlparse(authorization_response)
    return configured._replace(query=actual.query, fragment=actual.fragment).geturl()


class GoogleOAuthService:
    def __init__(
        self,
        metadata_store: MetadataStore | None = None,
        credential_store: GoogleCredentialStore | None = None,
    ):
        self.metadata_store = metadata_store or MetadataStore()
        self.credential_store = credential_store or GoogleCredentialStore(
            metadata_store=self.metadata_store
        )

    def _flow(self, scopes: list[str], state: str | None = None) -> Flow:
        if not settings.GOOGLE_REDIRECT_URI:
            raise ValueError("Set GOOGLE_REDIRECT_URI before starting Google OAuth.")

        _allow_local_http_oauth()
        return Flow.from_client_config(
            load_google_client_config(),
            scopes=scopes,
            redirect_uri=settings.GOOGLE_REDIRECT_URI,
            state=state,
        )

    def authorization_url(
        self,
        user_id: str,
        service: str = "workspace",
        login_hint: str | None = None,
    ) -> str:
        if service not in SERVICE_CONFIG:
            raise ValueError(
                "service must be one of: workspace, drive, gmail"
            )

        provider, scopes = SERVICE_CONFIG[service]
        state = secrets.token_urlsafe(32)
        flow = self._flow(scopes=scopes, state=state)
        url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="false",
            prompt="consent",
            **({"login_hint": login_hint} if login_hint else {}),
        )
        self.metadata_store.save_oauth_state(
            user_id=user_id,
            provider=provider,
            state=state,
            scopes=scopes,
            code_verifier=getattr(flow, "code_verifier", None),
        )
        return url

    def handle_callback(self, state: str, authorization_response: str) -> dict:
        oauth_state = self.metadata_store.pop_oauth_state(state=state)
        if not oauth_state:
            raise ValueError("Invalid or expired OAuth state.")

        flow = self._flow(scopes=oauth_state["scopes"], state=state)
        if oauth_state.get("code_verifier"):
            flow.code_verifier = oauth_state["code_verifier"]
        flow.fetch_token(
            authorization_response=_configured_authorization_response(
                authorization_response
            )
        )
        account_id = self.credential_store.save_credentials(
            user_id=oauth_state["user_id"],
            credentials=flow.credentials,
            provider=oauth_state["provider"],
        )

        return {
            "account_id": account_id,
            "user_id": oauth_state["user_id"],
            "provider": oauth_state["provider"],
            "scopes": list(flow.credentials.scopes or []),
        }
