from app.qdrant_store import QdrantStore

store = QdrantStore()

existing = [c.name for c in store.client.get_collections().collections]

if store.collection_name in existing:
    store.client.delete_collection(collection_name=store.collection_name)
    print(f"Deleted collection: {store.collection_name}")
else:
    print(f"Collection does not exist: {store.collection_name}")

print("Qdrant reset complete.")