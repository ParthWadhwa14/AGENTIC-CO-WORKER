from pathlib import Path
from uuid import uuid4

from app.models import ParsedElement
from app.loaders.text_structure import split_text_into_sections


class TXTLoader:
    source_type = "txt"

    def load(self, file_path: str, document_id: str | None = None) -> list[ParsedElement]:
        document_id = document_id or str(uuid4())
        path = Path(file_path)

        text = path.read_text(encoding="utf-8", errors="ignore")

        elements: list[ParsedElement] = []
        sections = split_text_into_sections(text)

        for section_index, section in enumerate(sections):
            if not section.text.strip():
                continue

            elements.append(
                ParsedElement(
                    document_id=document_id,
                    source_type=self.source_type,
                    file_name=path.name,
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
                    },
                )
            )

        return elements
