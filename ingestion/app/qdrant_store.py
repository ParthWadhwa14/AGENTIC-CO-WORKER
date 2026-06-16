from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
)
from app.config import settings
from app.models import Chunk
from app.embeddings import Embedder


class QdrantStore:
    def __init__(self):
        self.client = QdrantClient(
            url=settings.QDRANT_URL,
            api_key=settings.QDRANT_API_KEY,
        )
        self.collection_name = settings.QDRANT_COLLECTION
        self.embedder = Embedder()

    def ensure_collection(self, vector_size: int):
        existing = [c.name for c in self.client.get_collections().collections]

        if self.collection_name in existing:
            return

        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(
                size=vector_size,
                distance=Distance.COSINE,
            ),
        )

    def upsert_chunks(self, chunks: list[Chunk], batch_size: int = 64):
        if not chunks:
            return

        texts = [chunk.embedding_text or chunk.text for chunk in chunks]
        vectors = self.embedder.embed_texts(texts)

        self.ensure_collection(vector_size=len(vectors[0]))

        points = []

        for chunk, vector in zip(chunks, vectors):
            payload = {
                "chunk_id": chunk.chunk_id,
                "document_id": chunk.document_id,
                "source_type": chunk.source_type,
                "chunk_type": chunk.chunk_type,
                "text": chunk.text,
                "embedding_text": chunk.embedding_text,

                "file_name": chunk.file_name,
                "page_number": chunk.page_number,
                "sheet_name": chunk.sheet_name,
                "slide_number": chunk.slide_number,
                "row_start": chunk.row_start,
                "row_end": chunk.row_end,
                "heading_path": chunk.heading_path,

                "metadata": chunk.metadata,
            }

            points.append(
                PointStruct(
                    id=chunk.chunk_id,
                    vector=vector,
                    payload=payload,
                )
            )

        for i in range(0, len(points), batch_size):
            batch = points[i:i + batch_size]

            self.client.upsert(
                collection_name=self.collection_name,
                points=batch,
            )

    def delete_document_chunks(self, document_id: str):
        from qdrant_client.models import (
            Filter,
            FieldCondition,
            FilterSelector,
            MatchValue,
        )

        existing = [c.name for c in self.client.get_collections().collections]
        if self.collection_name not in existing:
            return

        self.client.delete(
            collection_name=self.collection_name,
            points_selector=FilterSelector(
                filter=Filter(
                    must=[
                        FieldCondition(
                            key="document_id",
                            match=MatchValue(value=document_id),
                        )
                    ]
                )
            ),
        )

    def search(
        self,
        query: str,
        limit: int = 8,
        source_type: str | None = None,
        document_ids: list[str] | None = None,
    ):
        query_vector = self.embedder.embed_text(query)

        query_filter = None
        conditions = []

        if source_type:
            from qdrant_client.models import FieldCondition, MatchValue

            conditions.append(
                FieldCondition(
                    key="source_type",
                    match=MatchValue(value=source_type),
                )
            )

        if document_ids:
            from qdrant_client.models import FieldCondition, MatchAny

            conditions.append(
                FieldCondition(
                    key="document_id",
                    match=MatchAny(any=document_ids),
                )
            )

        if conditions:
            from qdrant_client.models import Filter

            query_filter = Filter(must=conditions)

        response = self.client.query_points(
        collection_name=settings.QDRANT_COLLECTION,
        query=query_vector,
        limit=limit,
        query_filter=query_filter,
        with_payload=True,
)

        results = response.points

        return results

    def search_documents(
        self,
        query: str,
        document_ids: list[str],
        limit: int = 8,
    ):
        from qdrant_client.models import Filter, FieldCondition, MatchAny

        if not document_ids:
            return []

        query_vector = self.embedder.embed_text(query)
        response = self.client.query_points(
            collection_name=settings.QDRANT_COLLECTION,
            query=query_vector,
            limit=limit,
            query_filter=Filter(
                must=[
                    FieldCondition(
                        key="document_id",
                        match=MatchAny(any=document_ids),
                    )
                ]
            ),
            with_payload=True,
        )
        return response.points
