import json
from pathlib import Path

from app.config import settings


def load_google_client_config() -> dict:
    if settings.GOOGLE_CLIENT_CONFIG_JSON:
        return json.loads(settings.GOOGLE_CLIENT_CONFIG_JSON)

    if settings.GOOGLE_CLIENT_SECRETS_FILE:
        with Path(settings.GOOGLE_CLIENT_SECRETS_FILE).open() as handle:
            return json.load(handle)

    if settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET:
        return {
            "web": {
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": (
                    "https://www.googleapis.com/oauth2/v1/certs"
                ),
                "redirect_uris": [settings.GOOGLE_OAUTH_REDIRECT_URI],
            }
        }

    raise ValueError(
        "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET, or set "
        "GOOGLE_CLIENT_CONFIG_JSON / GOOGLE_CLIENT_SECRETS_FILE before "
        "starting Google OAuth."
    )


def google_client_secrets() -> tuple[str | None, str | None]:
    config = load_google_client_config()
    client = config.get("web") or config.get("installed") or {}
    return client.get("client_id"), client.get("client_secret")
