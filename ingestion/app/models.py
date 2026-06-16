from typing import Any, Optional
from pydantic import BaseModel, Field
from uuid import uuid4


class ParsedElement(BaseModel):
    document_id: str
    source_type: str

    text: str
    element_type: str = "text"

    file_name: Optional[str] = None
    page_number: Optional[int] = None
    sheet_name: Optional[str] = None
    slide_number: Optional[int] = None

    row_start: Optional[int] = None
    row_end: Optional[int] = None

    heading_path: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Chunk(BaseModel):
    chunk_id: str = Field(default_factory=lambda: str(uuid4()))
    document_id: str
    source_type: str
    chunk_type: str

    text: str
    embedding_text: Optional[str] = None

    file_name: Optional[str] = None
    page_number: Optional[int] = None
    sheet_name: Optional[str] = None
    slide_number: Optional[int] = None
    row_start: Optional[int] = None
    row_end: Optional[int] = None

    heading_path: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)