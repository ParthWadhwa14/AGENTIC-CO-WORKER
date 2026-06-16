from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, RedirectResponse

from app.storage.metadata_store import MetadataStore


router = APIRouter(prefix="/references", tags=["references"])


@router.get("/{document_id}/open")
def open_reference(document_id: str):
    document = MetadataStore().get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if document.get("web_url"):
        return RedirectResponse(document["web_url"])

    if document.get("source") == "gmail" and document.get("external_id"):
        return RedirectResponse(
            f"https://mail.google.com/mail/u/0/#all/{document['external_id']}"
        )

    local_path = document.get("local_path")
    if not local_path:
        raise HTTPException(
            status_code=404,
            detail="No local or web reference is available for this document.",
        )

    path = Path(local_path)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Local reference file not found")

    return FileResponse(path)
