import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")
load_dotenv()


def parse_scopes(env_name: str, defaults: list[str]) -> list[str]:
    raw = os.getenv(env_name)
    if not raw:
        return defaults
    return [scope for scope in raw.replace(",", " ").split() if scope]


def normalize_google_scopes(scopes: list[str]) -> list[str]:
    replacements = {
        "email": "https://www.googleapis.com/auth/userinfo.email",
        "profile": "https://www.googleapis.com/auth/userinfo.profile",
    }
    normalized = []
    seen = set()
    for scope in scopes:
        canonical = replacements.get(scope, scope)
        if canonical not in seen:
            normalized.append(canonical)
            seen.add(canonical)
    return normalized


def ensure_google_scopes(scopes: list[str], required: list[str]) -> list[str]:
    return normalize_google_scopes(scopes + required)


DEFAULT_GENERATION_MODEL = "openai/gpt-oss-120b"
DEFAULT_FALLBACK_GENERATION_MODEL = "openai/gpt-oss-20b"
LEGACY_GOOGLE_MODEL_PREFIXES = ("gem",)


def generation_model_from_env(
    env_name: str,
    default: str,
    fallback_for_legacy: str,
) -> str:
    model = os.getenv(env_name, default).strip()
    if not model or model.startswith(LEGACY_GOOGLE_MODEL_PREFIXES):
        return fallback_for_legacy
    return model


GOOGLE_DEFAULT_BASE_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]
GOOGLE_DEFAULT_DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive.metadata.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/documents.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]
GOOGLE_DEFAULT_GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
]
GOOGLE_DEFAULT_DOCS_WRITE_SCOPES = [
    "https://www.googleapis.com/auth/documents",
]
GOOGLE_DEFAULT_SHEETS_WRITE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]
GOOGLE_DEFAULT_READONLY_SCOPES = (
    GOOGLE_DEFAULT_BASE_SCOPES
    + GOOGLE_DEFAULT_GMAIL_SCOPES
    + GOOGLE_DEFAULT_DRIVE_SCOPES
    + GOOGLE_DEFAULT_DOCS_WRITE_SCOPES
    + GOOGLE_DEFAULT_SHEETS_WRITE_SCOPES
)


class Settings:
    QDRANT_URL: str = os.getenv("QDRANT_URL", "http://localhost:6333")
    QDRANT_COLLECTION: str = os.getenv(
        "QDRANT_COLLECTION",
        "personal_workspace_chunks"
    )
    EMBEDDING_MODEL: str = os.getenv(
        "EMBEDDING_MODEL",
        "BAAI/bge-small-en-v1.5"
    )
    GROQ_API_KEY: str | None = os.getenv("GROQ_API_KEY")
    SERPER_API_KEY: str | None = os.getenv("SERPER_API_KEY")
    DEFAULT_REGION: str = os.getenv("DEFAULT_REGION", "India")
    DEFAULT_TIMEZONE: str = os.getenv("DEFAULT_TIMEZONE", "Asia/Kolkata")
    GENERATION_MODEL: str = generation_model_from_env(
        "GENERATION_MODEL",
        DEFAULT_GENERATION_MODEL,
        DEFAULT_GENERATION_MODEL,
    )
    FALLBACK_GENERATION_MODEL: str = generation_model_from_env(
        "FALLBACK_GENERATION_MODEL",
        DEFAULT_FALLBACK_GENERATION_MODEL,
        DEFAULT_FALLBACK_GENERATION_MODEL,
    )
    GROQ_CONTEXT_CHAR_LIMIT: int = int(
        os.getenv("GROQ_CONTEXT_CHAR_LIMIT", "70000")
    )
    GROQ_MAX_OUTPUT_TOKENS: int = int(os.getenv("GROQ_MAX_OUTPUT_TOKENS", "4096"))
    GENERATION_TEMPERATURE: float = float(
        os.getenv("GENERATION_TEMPERATURE", "0.2")
    )
    DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'app.db'}")
    METADATA_DATABASE_URL: str = os.getenv(
        "METADATA_DATABASE_URL",
        f"sqlite:///{BASE_DIR / 'app.db'}",
    )
    SUPABASE_URL: str | None = os.getenv("SUPABASE_URL")
    SUPABASE_ANON_KEY: str | None = os.getenv("SUPABASE_ANON_KEY")
    SUPABASE_SERVICE_ROLE_KEY: str | None = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    SUPABASE_UPLOAD_BUCKET: str = os.getenv(
        "SUPABASE_UPLOAD_BUCKET",
        "user-uploads",
    )
    UPLOAD_DIR: Path = Path(os.getenv("UPLOAD_DIR", BASE_DIR / "uploaded_files"))
    DRIVE_DOWNLOAD_DIR: Path = Path(
        os.getenv("DRIVE_DOWNLOAD_DIR", BASE_DIR / "synced_drive_files")
    )
    GOOGLE_CLIENT_SECRETS_FILE: str | None = os.getenv(
        "GOOGLE_CLIENT_SECRETS_FILE"
    )
    GOOGLE_CLIENT_CONFIG_JSON: str | None = os.getenv(
        "GOOGLE_CLIENT_CONFIG_JSON"
    )
    GOOGLE_CLIENT_ID: str | None = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET: str | None = os.getenv("GOOGLE_CLIENT_SECRET")
    GOOGLE_OAUTH_REDIRECT_URI: str = os.getenv(
        "GOOGLE_OAUTH_REDIRECT_URI",
        os.getenv(
            "GOOGLE_REDIRECT_URI",
            "http://localhost:8000/auth/google/callback",
        ),
    )
    FRONTEND_URL: str = os.getenv(
        "FRONTEND_URL",
        "http://localhost:3000",
    )
    TOKEN_ENCRYPTION_KEY: str | None = os.getenv("TOKEN_ENCRYPTION_KEY")
    GOOGLE_BASE_SCOPES: list[str] = normalize_google_scopes(
        parse_scopes("GOOGLE_BASE_SCOPES", GOOGLE_DEFAULT_BASE_SCOPES)
    )
    GOOGLE_DRIVE_SCOPES: list[str] = ensure_google_scopes(
        parse_scopes("GOOGLE_DRIVE_SCOPES", GOOGLE_DEFAULT_DRIVE_SCOPES),
        GOOGLE_DEFAULT_DRIVE_SCOPES + GOOGLE_DEFAULT_DOCS_WRITE_SCOPES
        + GOOGLE_DEFAULT_SHEETS_WRITE_SCOPES,
    )
    GOOGLE_GMAIL_SCOPES: list[str] = ensure_google_scopes(
        parse_scopes("GOOGLE_GMAIL_SCOPES", GOOGLE_DEFAULT_GMAIL_SCOPES),
        GOOGLE_DEFAULT_GMAIL_SCOPES,
    )
    GOOGLE_READONLY_SCOPES: list[str] = ensure_google_scopes(
        parse_scopes("GOOGLE_SCOPES", GOOGLE_DEFAULT_READONLY_SCOPES),
        GOOGLE_DEFAULT_READONLY_SCOPES,
    )


settings = Settings()
