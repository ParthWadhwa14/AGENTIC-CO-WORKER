import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, File, Form, UploadFile

from app.config import settings
from app.services.ingestion_jobs import process_ingestion_job
from app.storage.metadata_store import MetadataStore
from app.storage.supabase_storage import upload_file_to_supabase


router = APIRouter(prefix="/upload", tags=["upload"])
TABLE_CONTENT_TYPES = {
    "text/csv",
    "application/csv",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def safe_filename(filename: str) -> str:
    name = Path(filename).name
    return name.replace("/", "_").replace("\\", "_")


@router.post("")
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user_id: str = Form(...),
):
    metadata_store = MetadataStore()
    document_id = str(uuid4())
    original_name = safe_filename(file.filename or "uploaded_file")

    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stored_path = settings.UPLOAD_DIR / f"{document_id}_{original_name}"

    with stored_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    storage_bucket = None
    storage_path = None
    supabase_upload = upload_file_to_supabase(
        local_path=str(stored_path),
        storage_path=f"{user_id}/uploads/{document_id}/{original_name}",
        content_type=file.content_type,
    )
    if supabase_upload:
        storage_bucket = supabase_upload["bucket"]
        storage_path = supabase_upload["path"]

    metadata_store.create_document(
        document_id=document_id,
        user_id=user_id,
        source="upload",
        file_name=original_name,
        mime_type=file.content_type,
        local_path=str(stored_path),
        storage_bucket=storage_bucket,
        storage_path=storage_path,
        index_status=(
            "table_source"
            if file.content_type in TABLE_CONTENT_TYPES
            or original_name.lower().endswith((".csv", ".xlsx", ".xls"))
            else "queued"
        ),
    )
    if (
        file.content_type in TABLE_CONTENT_TYPES
        or original_name.lower().endswith((".csv", ".xlsx", ".xls"))
    ):
        return {
            "document_id": document_id,
            "job_id": None,
            "file_name": original_name,
            "stored_path": str(stored_path),
            "storage_bucket": storage_bucket,
            "storage_path": storage_path,
            "status": "table_source",
        }

    job_id = metadata_store.create_ingestion_job(
        user_id=user_id,
        document_id=document_id,
        reason="upload",
    )

    background_tasks.add_task(
        process_ingestion_job,
        job_id,
        document_id,
        str(stored_path),
    )

    return {
        "document_id": document_id,
        "job_id": job_id,
        "file_name": original_name,
        "stored_path": str(stored_path),
        "storage_bucket": storage_bucket,
        "storage_path": storage_path,
        "status": "queued",
    }
