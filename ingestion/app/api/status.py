from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from qdrant_client import QdrantClient

from app.config import settings
from app.qdrant_store import QdrantStore
from app.services.runtime_context import runtime_context
from app.storage.metadata_store import MetadataStore


router = APIRouter(tags=["status"])


class CleanupDocumentsRequest(BaseModel):
    user_id: str
    keep_document_ids: list[str] = Field(default_factory=list)


@router.get("/setup/status")
def setup_status():
    qdrant_status = {
        "reachable": False,
        "collection_exists": False,
        "chunk_count": 0,
        "error": None,
    }
    try:
        client = QdrantClient(url=settings.QDRANT_URL)
        collections = [c.name for c in client.get_collections().collections]
        qdrant_status["reachable"] = True
        qdrant_status["collection_exists"] = (
            settings.QDRANT_COLLECTION in collections
        )
        if qdrant_status["collection_exists"]:
            qdrant_status["chunk_count"] = client.count(
                collection_name=settings.QDRANT_COLLECTION,
                exact=True,
            ).count
    except Exception as exc:
        qdrant_status["error"] = str(exc)

    return {
        "google_oauth_configured": bool(
            settings.GOOGLE_CLIENT_CONFIG_JSON
            or settings.GOOGLE_CLIENT_SECRETS_FILE
            or (settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)
        ),
        "groq_api_key_configured": bool(settings.GROQ_API_KEY),
        "serper_api_key_configured": bool(settings.SERPER_API_KEY),
        "token_encryption_configured": bool(settings.TOKEN_ENCRYPTION_KEY),
        "frontend_url": settings.FRONTEND_URL,
        "google_oauth_redirect_uri": settings.GOOGLE_OAUTH_REDIRECT_URI,
        "generation_model": settings.GENERATION_MODEL,
        "fallback_generation_model": settings.FALLBACK_GENERATION_MODEL,
        "runtime_context": runtime_context(),
        "qdrant": qdrant_status,
    }


@router.get("/documents/{document_id}")
def get_document(document_id: str):
    document = MetadataStore().get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.get("/documents")
def list_documents(
    user_id: str = Query(...),
    limit: int = Query(100, ge=1, le=500),
    include_deleted: bool = Query(False),
):
    return {
        "user_id": user_id,
        "documents": MetadataStore().list_documents(
            user_id,
            limit=limit,
            include_deleted=include_deleted,
        ),
    }


@router.post("/documents/cleanup-chat")
def cleanup_chat_documents(request: CleanupDocumentsRequest):
    metadata_store = MetadataStore()
    documents = metadata_store.cleanup_chat_indexed_documents(
        user_id=request.user_id,
        keep_document_ids=request.keep_document_ids,
    )
    qdrant_errors = []
    if documents:
        qdrant = QdrantStore()
        for document in documents:
            try:
                qdrant.delete_document_chunks(document["id"])
            except Exception as exc:
                qdrant_errors.append(
                    {
                        "document_id": document["id"],
                        "error": str(exc),
                    }
                )

    return {
        "user_id": request.user_id,
        "deleted_count": len(documents),
        "deleted_document_ids": [document["id"] for document in documents],
        "deleted_local_files": [
            document["local_path"]
            for document in documents
            if document.get("local_file_deleted")
        ],
        "local_file_errors": [
            {
                "document_id": document["id"],
                "error": document["local_file_error"],
            }
            for document in documents
            if document.get("local_file_error")
        ],
        "preserved_document_ids": request.keep_document_ids,
        "qdrant_errors": qdrant_errors,
    }


@router.get("/ingestion-jobs/{job_id}")
def get_ingestion_job(job_id: str):
    job = MetadataStore().get_ingestion_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Ingestion job not found")
    return job
