from fastembed import TextEmbedding
from app.config import settings


class Embedder:
    def __init__(self):
        self.model = TextEmbedding(model_name=settings.EMBEDDING_MODEL)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        embeddings = list(self.model.embed(texts))
        return [embedding.tolist() for embedding in embeddings]

    def embed_text(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]