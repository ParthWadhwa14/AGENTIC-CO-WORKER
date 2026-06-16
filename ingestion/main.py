import argparse
from pathlib import Path
from uuid import uuid4

from app.chunking import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    chunk_text_elements,
    chunk_table_rows,
    chunk_pptx_slides,
)
from app.qdrant_store import QdrantStore
from app.query_engine import QueryEngine

from app.loaders.pdf_loader import PDFLoader
from app.loaders.txt_loader import TXTLoader
from app.loaders.csv_profile_loader import CSVProfileLoader
from app.loaders.xlsx_loader import XLSXLoader
from app.loaders.pptx_loader import PPTXLoader


def detect_loader(file_path: str):
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        return PDFLoader(), "text"

    if suffix == ".txt":
        return TXTLoader(), "text"

    if suffix == ".csv":
        return CSVProfileLoader(), "text"

    if suffix in [".xlsx", ".xls"]:
        return XLSXLoader(), "table"

    if suffix == ".pptx":
        return PPTXLoader(), "pptx"

    raise ValueError(f"Unsupported file type: {suffix}")


def ingest_file(
    file_path: str,
    document_id: str | None = None,
    store: QdrantStore | None = None,
):
    document_id = document_id or str(uuid4())

    loader, chunking_mode = detect_loader(file_path)

    print(f"Ingesting: {file_path}")
    print(f"Document ID: {document_id}")
    print(f"Chunking mode: {chunking_mode}")

    elements = loader.load(file_path, document_id=document_id)

    if chunking_mode == "text":
        chunks = chunk_text_elements(
            elements,
            chunk_size=DEFAULT_CHUNK_SIZE,
            chunk_overlap=DEFAULT_CHUNK_OVERLAP,
        )

    elif chunking_mode == "table":
        chunks = chunk_table_rows(elements)

    elif chunking_mode == "pptx":
        chunks = chunk_pptx_slides(elements)

    else:
        raise ValueError(f"Unknown chunking mode: {chunking_mode}")

    print(f"Parsed elements: {len(elements)}")
    print(f"Created chunks: {len(chunks)}")

    store = store or QdrantStore()
    store.upsert_chunks(chunks)

    print("Ingestion complete.")

    return {
        "document_id": document_id,
        "chunks": len(chunks),
    }


def ask_query(query: str, source_type: str | None = None):
    engine = QueryEngine()

    if source_type == "csv":
        result = engine.answer_csv_query_simple(query)
        print(result)
        return result

    store = QdrantStore()
    results = store.search(
        query=query,
        limit=5,
        source_type=source_type,
    )

    for i, result in enumerate(results, start=1):
        payload = result.payload

        print("=" * 80)
        print(f"Result {i}")
        print(f"Score: {result.score}")
        print(f"File: {payload.get('file_name')}")
        print(f"Source: {payload.get('source_type')}")
        print(f"Chunk type: {payload.get('chunk_type')}")
        print("-" * 80)
        print(payload.get("text", "")[:1000])
        print()

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--file",
        type=str,
        default=None,
        help="Path to file to ingest"
    )

    parser.add_argument(
        "--query",
        type=str,
        default=None,
        help="Query to ask"
    )

    parser.add_argument(
        "--source-type",
        type=str,
        default=None,
        help="Optional source type: pdf, txt, csv, xlsx, pptx"
    )

    args = parser.parse_args()

    if args.file:
        ingest_file(args.file)

    if args.query:
        ask_query(args.query, source_type=args.source_type)
