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
        priority_document_ids: list[str] | None = None,
        fallback_to_default: bool = True,
    ) -> tuple[list[RetrievedChunk], list[dict]]:
        all_results = []
        source_types = source_types or DEFAULT_SOURCE_TYPES
        errors: list[str] = []
        priority_document_ids = priority_document_ids or []

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
            if priority_document_ids:
                try:
                    all_results.extend(
                        self.store.search_documents(
                            query=query,
                            document_ids=priority_document_ids,
                            limit=limit,
                        )
                    )
                except Exception as exc:
                    errors.append(f"priority_documents: {exc}")

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

        if (
            fallback_to_default
            and not all_results
            and not document_ids
            and source_types != DEFAULT_SOURCE_TYPES
        ):
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

        document_status_cache: dict[str, str | None] = {}
        active_results = []
        for result in all_results:
            payload = result.payload or {}
            document_id = payload.get("document_id")
            if document_id and document_id not in document_status_cache:
                document = self.metadata_store.get_document(document_id)
                document_status_cache[document_id] = (
                    document.get("index_status") if document else None
                )
            if document_id and document_status_cache.get(document_id) == "deleted":
                continue
            active_results.append(result)

        priority_set = set(priority_document_ids)
        all_results = sorted(
            active_results,
            key=lambda result: (
                (result.payload or {}).get("document_id") in priority_set,
                result.score,
            ),
            reverse=True,
        )

        deduped_results = []
        seen_chunk_ids = set()
        for result in all_results:
            payload = result.payload or {}
            chunk_id = payload.get("chunk_id")
            if chunk_id and chunk_id in seen_chunk_ids:
                continue
            if chunk_id:
                seen_chunk_ids.add(chunk_id)
            deduped_results.append(result)
            if len(deduped_results) >= limit:
                break

        chunks: list[RetrievedChunk] = []
        references: list[dict] = []

        for index, result in enumerate(deduped_results, start=1):
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
