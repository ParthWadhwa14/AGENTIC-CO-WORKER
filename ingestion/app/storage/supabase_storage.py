from pathlib import Path

from app.config import settings


def supabase_storage_configured() -> bool:
    return bool(settings.SUPABASE_URL and settings.SUPABASE_SERVICE_ROLE_KEY)


def upload_file_to_supabase(
    local_path: str,
    storage_path: str,
    content_type: str | None = None,
    bucket: str | None = None,
) -> dict | None:
    if not supabase_storage_configured():
        return None

    from supabase import create_client

    client = create_client(
        settings.SUPABASE_URL,
        settings.SUPABASE_SERVICE_ROLE_KEY,
    )
    bucket_name = bucket or settings.SUPABASE_UPLOAD_BUCKET
    path = Path(local_path)

    with path.open("rb") as handle:
        file_options = {"content-type": content_type} if content_type else None
        result = client.storage.from_(bucket_name).upload(
            path=storage_path,
            file=handle.read(),
            file_options=file_options,
        )

    return {
        "bucket": bucket_name,
        "path": storage_path,
        "result": result,
    }
