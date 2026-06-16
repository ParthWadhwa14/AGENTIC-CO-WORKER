import fitz  # PyMuPDF
from pathlib import Path
from uuid import uuid4

from app.models import ParsedElement
from app.loaders.text_structure import split_text_into_sections


class PDFLoader:
    source_type = "pdf"

    def load(self, file_path: str, document_id: str | None = None) -> list[ParsedElement]:
        document_id = document_id or str(uuid4())
        path = Path(file_path)

        doc = fitz.open(file_path)
        elements: list[ParsedElement] = []

        for page_index, page in enumerate(doc):
            blocks = page.get_text("blocks")
            block_texts = [
                block[4].strip()
                for block in sorted(blocks, key=lambda block: (block[1], block[0]))
                if len(block) > 4 and block[4].strip()
            ]
            text = "\n\n".join(block_texts).strip()

            if not text:
                continue

            sections = split_text_into_sections(
                text,
                default_heading=f"Page {page_index + 1}"
            )

            for section_index, section in enumerate(sections):
                elements.append(
                    ParsedElement(
                        document_id=document_id,
                        source_type=self.source_type,
                        file_name=path.name,
                        page_number=page_index + 1,
                        element_type="section",
                        text=section.text,
                        heading_path=section.heading_path,
                        metadata={
                            "file_path": str(path),
                            "section_index": section_index,
                            "section_heading": (
                                section.heading_path[-1]
                                if section.heading_path else None
                            ),
                            "start_line": section.start_line,
                            "end_line": section.end_line,
                            "block_count": len(block_texts),
                        },
                    )
                )

        return elements
