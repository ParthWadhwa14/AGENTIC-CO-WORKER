from app.models import ParsedElement, Chunk

DEFAULT_CHUNK_SIZE = 500
DEFAULT_CHUNK_OVERLAP = 100
RECURSIVE_SEPARATORS = ["\n\n", "\n", ". ", "; ", ", ", " ", ""]


def simple_token_count(text: str) -> int:
    """
    Approximate token count.
    Good enough for chunking starter.
    Later replace with tiktoken or model-specific tokenizer.
    """
    return max(1, len(text.split()))


def _recursive_units(
    text: str,
    chunk_size: int,
    chunk_overlap: int,
    separators: list[str]
) -> list[str]:
    text = text.strip()

    if not text:
        return []

    if len(text) <= chunk_size:
        return [text]

    if not separators:
        stride = max(1, chunk_size - chunk_overlap)
        return [text[i:i + stride] for i in range(0, len(text), stride)]

    separator = separators[0]

    if separator and separator not in text:
        return _recursive_units(
            text,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=separators[1:],
        )

    if separator == "":
        stride = max(1, chunk_size - chunk_overlap)
        return [text[i:i + stride] for i in range(0, len(text), stride)]

    pieces = []
    raw_pieces = text.split(separator)

    for index, piece in enumerate(raw_pieces):
        if not piece:
            continue

        unit = piece if index == len(raw_pieces) - 1 else piece + separator

        if len(unit) <= chunk_size:
            pieces.append(unit)
            continue

        pieces.extend(
            _recursive_units(
                unit,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                separators=separators[1:],
            )
        )

    return pieces


def _overlap_tail(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""

    tail = text[-max_chars:]
    for separator in ["\n\n", "\n", ". ", " "]:
        split_at = tail.find(separator)
        if split_at > 0:
            return tail[split_at + len(separator):]

    return tail


def split_text_recursively(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP
) -> list[str]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than 0")

    if chunk_overlap < 0:
        raise ValueError("chunk_overlap cannot be negative")

    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")

    units = _recursive_units(
        text,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=RECURSIVE_SEPARATORS,
    )
    chunks: list[str] = []
    current = ""

    for unit in units:
        candidate = f"{current}{unit}" if current else unit

        if len(candidate) <= chunk_size:
            current = candidate
            continue

        if current.strip():
            chunks.append(current.strip())

        available_overlap = max(0, chunk_size - len(unit))
        overlap = _overlap_tail(current, min(chunk_overlap, available_overlap))
        current = f"{overlap}{unit}" if overlap else unit

        if len(current) > chunk_size:
            chunks.append(unit[:chunk_size].strip())
            current = unit[chunk_size - chunk_overlap:]

    if current.strip():
        chunks.append(current.strip())

    return chunks


def build_embedding_text(chunk: Chunk) -> str:
    heading = " > ".join(chunk.heading_path) if chunk.heading_path else "N/A"

    location_parts = []

    if chunk.page_number is not None:
        location_parts.append(f"Page: {chunk.page_number}")

    if chunk.sheet_name:
        location_parts.append(f"Sheet: {chunk.sheet_name}")

    if chunk.slide_number is not None:
        location_parts.append(f"Slide: {chunk.slide_number}")

    if chunk.row_start is not None and chunk.row_end is not None:
        location_parts.append(f"Rows: {chunk.row_start}-{chunk.row_end}")

    location = ", ".join(location_parts) if location_parts else "N/A"

    return f"""
Document: {chunk.file_name or "Unknown"}
Source type: {chunk.source_type}
Chunk type: {chunk.chunk_type}
Location: {location}
Section: {heading}

Content:
{chunk.text}
""".strip()


def chunk_text_elements(
    elements: list[ParsedElement],
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP
) -> list[Chunk]:
    chunks: list[Chunk] = []

    for element in elements:
        split_parts = split_text_recursively(
            element.text,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap
        )

        for split_index, part in enumerate(split_parts):
            metadata = {
                **element.metadata,
                "split_index": split_index,
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
            }
            chunk = Chunk(
                document_id=element.document_id,
                source_type=element.source_type,
                chunk_type=f"{element.source_type}_{element.element_type}",
                text=part,
                file_name=element.file_name,
                page_number=element.page_number,
                sheet_name=element.sheet_name,
                slide_number=element.slide_number,
                row_start=element.row_start,
                row_end=element.row_end,
                heading_path=element.heading_path,
                metadata=metadata,
            )
            chunk.embedding_text = build_embedding_text(chunk)
            chunks.append(chunk)

    return chunks


def chunk_table_rows(
    elements: list[ParsedElement],
    rows_per_chunk: int = 25
) -> list[Chunk]:
    """
    For CSV/XLSX row-group elements.
    Usually the loader will already create row-group ParsedElements,
    so this mostly wraps them into chunks.
    """
    chunks: list[Chunk] = []

    for element in elements:
        chunk = Chunk(
            document_id=element.document_id,
            source_type=element.source_type,
            chunk_type=f"{element.source_type}_row_group",
            text=element.text,
            file_name=element.file_name,
            sheet_name=element.sheet_name,
            row_start=element.row_start,
            row_end=element.row_end,
            metadata=element.metadata,
        )
        chunk.embedding_text = build_embedding_text(chunk)
        chunks.append(chunk)

    return chunks


def chunk_pptx_slides(elements: list[ParsedElement]) -> list[Chunk]:
    chunks: list[Chunk] = []

    for element in elements:
        chunk = Chunk(
            document_id=element.document_id,
            source_type=element.source_type,
            chunk_type="pptx_slide",
            text=element.text,
            file_name=element.file_name,
            slide_number=element.slide_number,
            metadata=element.metadata,
        )
        chunk.embedding_text = build_embedding_text(chunk)
        chunks.append(chunk)

    return chunks
