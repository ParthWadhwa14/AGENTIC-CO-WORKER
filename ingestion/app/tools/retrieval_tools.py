from app.agent.references import build_reference
from app.agent.state import RetrievedChunk
from app.qdrant_store import QdrantStore
from app.storage.metadata_store import MetadataStore


DEFAULT_SOURCE_TYPES = [
    "pdf",
    "txt",
    "pptx",
    "google_doc",
    "google_sheet",
    "csv",
    "xlsx",
    "gmail",
]


class RetrievalTools:
    def __init__(self):
        self.store = QdrantStore()
        self.metadata_store = MetadataStore()

    def search_workspace(
        self,
        query: str,
        source_types: list[str] | None = None,
        limit: int = 8,
        document_ids: list[str] | None = None,
    ) -> tuple[list[RetrievedChunk], list[dict]]:
        all_results = []
        source_types = source_types or DEFAULT_SOURCE_TYPES
        errors: list[str] = []

        if document_ids:
            try:
                all_results.extend(
                    self.store.search_documents(
                        query=query,
                        document_ids=document_ids,
                        limit=limit,
                    )
                )
            except Exception as exc:
                errors.append(f"selected_documents: {exc}")
        else:
            for source_type in source_types:
                try:
                    results = self.store.search(
                        query=query,
                        limit=limit,
                        source_type=source_type,
                    )
                    all_results.extend(results)
                except Exception as exc:
                    errors.append(f"{source_type}: {exc}")

        if not all_results and not document_ids and source_types != DEFAULT_SOURCE_TYPES:
            for source_type in DEFAULT_SOURCE_TYPES:
                if source_type in source_types:
                    continue
                try:
                    results = self.store.search(
                        query=query,
                        limit=limit,
                        source_type=source_type,
                    )
                    all_results.extend(results)
                except Exception as exc:
                    errors.append(f"{source_type}: {exc}")

        if not all_results and errors:
            raise RuntimeError("Workspace retrieval failed: " + " | ".join(errors))

        all_results = sorted(
            all_results,
            key=lambda result: result.score,
            reverse=True,
        )[:limit]

        chunks: list[RetrievedChunk] = []
        references: list[dict] = []

        for index, result in enumerate(all_results, start=1):
            payload = result.payload or {}
            reference = build_reference(
                payload,
                index=index,
                metadata_store=self.metadata_store,
            )
            reference["score"] = float(result.score)
            references.append(reference)

            metadata = payload.get("metadata") or {}
            chunks.append(
                RetrievedChunk(
                    chunk_id=payload.get("chunk_id"),
                    document_id=payload.get("document_id"),
                    source_type=payload.get("source_type") or "unknown",
                    file_name=payload.get("file_name"),
                    title=reference["title"],
                    text=payload.get("text") or "",
                    score=float(result.score),
                    metadata=metadata,
                    reference=reference,
                )
            )

        return chunks, references
