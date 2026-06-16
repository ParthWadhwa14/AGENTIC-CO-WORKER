from app.qdrant_store import QdrantStore
from app.storage.metadata_store import MetadataStore, utc_now
from main import ingest_file


def process_ingestion_job(
    job_id: str,
    document_id: str,
    local_path: str,
    metadata_store: MetadataStore | None = None,
) -> dict:
    store = metadata_store or MetadataStore()

    try:
        store.update_ingestion_job(job_id, status="running")
        store.update_document_status(document_id, index_status="indexing")

        QdrantStore().delete_document_chunks(document_id)
        result = ingest_file(local_path, document_id=document_id)

        store.update_ingestion_job(job_id, status="indexed")
        store.update_document_status(
            document_id,
            index_status="indexed",
            indexed_at=utc_now(),
            local_path=local_path,
        )
        return result

    except Exception as exc:
        error = str(exc)
        store.update_ingestion_job(job_id, status="failed", error=error)
        store.update_document_status(document_id, index_status="failed")
        raise
