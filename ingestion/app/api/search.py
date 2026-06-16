from fastapi import APIRouter, Query

from app.agent.references import build_reference
from app.qdrant_store import QdrantStore
from app.storage.metadata_store import MetadataStore


router = APIRouter(prefix="/search", tags=["search"])


@router.get("")
def search_workspace(
    query: str = Query(...),
    user_id: str | None = Query(None),
    source_type: str | None = Query(None),
    limit: int = Query(8, ge=1, le=50),
):
    document_ids = None
    if user_id:
        document_ids = [
            document["id"]
            for document in MetadataStore().list_documents(user_id, limit=500)
            if document.get("index_status") == "indexed"
        ]
        if not document_ids:
            return {
                "query": query,
                "source_type": source_type,
                "count": 0,
                "results": [],
            }

    results = QdrantStore().search(
        query=query,
        limit=limit,
        source_type=source_type,
        document_ids=document_ids,
    )
    metadata_store = MetadataStore()

    return {
        "query": query,
        "source_type": source_type,
        "count": len(results),
        "results": [
            {
                "score": result.score,
                "payload": result.payload,
                "reference": {
                    **build_reference(
                        result.payload,
                        index=index,
                        metadata_store=metadata_store,
                    ),
                    "score": float(result.score),
                },
            }
            for index, result in enumerate(results, start=1)
        ],
    }
