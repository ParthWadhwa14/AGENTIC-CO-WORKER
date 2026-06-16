import base64
import hashlib

from cryptography.fernet import Fernet
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

from app.config import settings
from app.services.google_client import google_client_secrets
from app.storage.metadata_store import MetadataStore


GOOGLE_PROVIDER = "google_workspace"
GOOGLE_DRIVE_PROVIDER = "google_drive"
GOOGLE_GMAIL_PROVIDER = "google_gmail"
GOOGLE_PROVIDER_FALLBACKS = {
    GOOGLE_DRIVE_PROVIDER: [GOOGLE_DRIVE_PROVIDER, GOOGLE_PROVIDER, "google"],
    GOOGLE_GMAIL_PROVIDER: [GOOGLE_GMAIL_PROVIDER, GOOGLE_PROVIDER, "google"],
    GOOGLE_PROVIDER: [GOOGLE_PROVIDER, "google"],
}


class TokenCipher:
    def __init__(self, key: str | None = None):
        key = key or settings.TOKEN_ENCRYPTION_KEY
        if not key:
            raise ValueError(
                "TOKEN_ENCRYPTION_KEY is required before storing OAuth tokens. "
                "Generate one with: python -c "
                "\"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )

        self.fernet = Fernet(self._normalize_key(key))

    def _normalize_key(self, key: str) -> bytes:
        raw = key.encode()
        try:
            Fernet(raw)
            return raw
        except ValueError:
            digest = hashlib.sha256(raw).digest()
            return base64.urlsafe_b64encode(digest)

    def encrypt(self, value: str | None) -> str | None:
        if value is None:
            return None
        return self.fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str | None) -> str | None:
        if value is None:
            return None
        return self.fernet.decrypt(value.encode()).decode()


class GoogleCredentialStore:
    def __init__(
        self,
        metadata_store: MetadataStore | None = None,
        cipher: TokenCipher | None = None,
    ):
        self.metadata_store = metadata_store or MetadataStore()
        self.cipher = cipher or TokenCipher()

    def save_credentials(
        self,
        user_id: str,
        credentials: Credentials,
        provider: str = GOOGLE_PROVIDER,
    ) -> str:
        return self.metadata_store.upsert_connected_account(
            user_id=user_id,
            provider=provider,
            access_token_encrypted=self.cipher.encrypt(credentials.token),
            refresh_token_encrypted=self.cipher.encrypt(credentials.refresh_token),
            scopes=list(credentials.scopes or settings.GOOGLE_READONLY_SCOPES),
            expires_at=(
                credentials.expiry.isoformat()
                if credentials.expiry else None
            ),
        )

    def get_credentials(
        self,
        user_id: str,
        provider: str = GOOGLE_PROVIDER,
    ) -> Credentials:
        account = None
        selected_provider = provider
        for candidate in GOOGLE_PROVIDER_FALLBACKS.get(provider, [provider]):
            account = self.metadata_store.get_connected_account(
                user_id=user_id,
                provider=candidate,
            )
            if account:
                selected_provider = candidate
                break

        if not account:
            raise ValueError(
                f"No {provider} account connected for user_id={user_id}"
            )

        client_id, client_secret = google_client_secrets()
        credentials = Credentials(
            token=self.cipher.decrypt(account["access_token_encrypted"]),
            refresh_token=self.cipher.decrypt(account["refresh_token_encrypted"]),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=account["scopes"] or settings.GOOGLE_READONLY_SCOPES,
        )

        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
            self.save_credentials(user_id, credentials, provider=selected_provider)

        return credentials
