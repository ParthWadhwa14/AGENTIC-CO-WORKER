from fastapi import APIRouter, HTTPException, Query
from qdrant_client import QdrantClient

from app.config import settings
from app.services.runtime_context import runtime_context
from app.storage.metadata_store import MetadataStore


router = APIRouter(tags=["status"])


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
        "google_api_key_configured": bool(settings.GOOGLE_API_KEY),
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
):
    return {
        "user_id": user_id,
        "documents": MetadataStore().list_documents(user_id, limit=limit),
    }


@router.get("/ingestion-jobs/{job_id}")
def get_ingestion_job(job_id: str):
    job = MetadataStore().get_ingestion_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Ingestion job not found")
    return job
