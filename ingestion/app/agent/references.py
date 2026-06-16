from urllib.parse import urlencode

from app.storage.metadata_store import MetadataStore


def build_reference(
    payload: dict,
    index: int,
    metadata_store: MetadataStore | None = None,
) -> dict:
    metadata = payload.get("metadata") or {}
    document_id = payload.get("document_id")
    source_type = payload.get("source_type")
    file_name = payload.get("file_name") or metadata.get("subject") or "Source"

    location_parts = []
    if payload.get("page_number") is not None:
        location_parts.append(f"page {payload['page_number']}")
    if payload.get("slide_number") is not None:
        location_parts.append(f"slide {payload['slide_number']}")
    if payload.get("sheet_name"):
        location_parts.append(f"sheet {payload['sheet_name']}")
    if metadata.get("section_heading"):
        location_parts.append(str(metadata["section_heading"]))
    if metadata.get("subject"):
        location_parts.append(str(metadata["subject"]))

    open_url = None
    if document_id:
        query = urlencode({"ref": index})
        open_url = f"/references/{document_id}/open?{query}"

    if not open_url and source_type == "gmail" and metadata.get("gmail_message_id"):
        open_url = (
            "https://mail.google.com/mail/u/0/#all/"
            f"{metadata['gmail_message_id']}"
        )

    return {
        "ref": index,
        "document_id": document_id,
        "chunk_id": payload.get("chunk_id"),
        "source_type": source_type,
        "title": file_name,
        "file_name": file_name,
        "open_url": open_url,
        "score": None,
        "metadata": {
            "page_number": payload.get("page_number"),
            "sheet_name": payload.get("sheet_name"),
            "slide_number": payload.get("slide_number"),
            "location": ", ".join(location_parts),
            "heading_path": payload.get("heading_path") or [],
            **metadata,
        },
    }
