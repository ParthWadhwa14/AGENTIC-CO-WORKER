from uuid import uuid4

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

from app.models import ParsedElement
from app.loaders.text_structure import clean_heading, split_text_into_sections


class GoogleDocsLoader:
    source_type = "google_doc"

    def __init__(self, credentials: Credentials):
        self.drive_service = build("drive", "v3", credentials=credentials)
        self.docs_service = build("docs", "v1", credentials=credentials)

    def _load_from_plain_text(
        self,
        google_doc_id: str,
        document_id: str,
        file_name: str | None = None
    ) -> list[ParsedElement]:
        exported = self.drive_service.files().export(
            fileId=google_doc_id,
            mimeType="text/plain"
        ).execute()

        text = exported.decode("utf-8", errors="ignore")
        elements: list[ParsedElement] = []
        sections = split_text_into_sections(text)

        for section_index, section in enumerate(sections):
            elements.append(
                ParsedElement(
                    document_id=document_id,
                    source_type=self.source_type,
                    file_name=file_name or google_doc_id,
                    element_type="section",
                    text=section.text,
                    heading_path=section.heading_path,
                    metadata={
                        "google_doc_id": google_doc_id,
                        "section_index": section_index,
                        "section_heading": (
                            section.heading_path[-1]
                            if section.heading_path else None
                        ),
                        "start_line": section.start_line,
                        "end_line": section.end_line,
                        "structure_source": "plain_text_export",
                    },
                )
            )

        return elements

    def _heading_level(self, named_style_type: str | None) -> int | None:
        if not named_style_type:
            return None

        if named_style_type == "TITLE":
            return 1

        if named_style_type == "SUBTITLE":
            return 2

        if named_style_type.startswith("HEADING_"):
            try:
                return int(named_style_type.rsplit("_", 1)[1])
            except ValueError:
                return None

        return None

    def _paragraph_text(self, paragraph: dict) -> str:
        text_parts = []

        for element in paragraph.get("elements", []):
            text_run = element.get("textRun")
            if not text_run:
                continue

            text_parts.append(text_run.get("content", ""))

        return "".join(text_parts).strip()

    def load(
        self,
        google_doc_id: str,
        document_id: str | None = None,
        file_name: str | None = None
    ) -> list[ParsedElement]:
        document_id = document_id or str(uuid4())

        try:
            document = self.docs_service.documents().get(
                documentId=google_doc_id
            ).execute()
        except Exception:
            return self._load_from_plain_text(
                google_doc_id=google_doc_id,
                document_id=document_id,
                file_name=file_name,
            )

        title = file_name or document.get("title") or google_doc_id
        elements: list[ParsedElement] = []
        current_heading_path: list[str] = []
        current_lines: list[str] = []
        section_start: int | None = None
        section_end: int | None = None
        section_heading: str | None = None

        def flush_section() -> None:
            nonlocal current_lines, section_start, section_end, section_heading

            section_text = "\n".join(current_lines).strip()
            if section_text:
                section_index = len(elements)
                elements.append(
                    ParsedElement(
                        document_id=document_id,
                        source_type=self.source_type,
                        file_name=title,
                        element_type="section",
                        text=section_text,
                        heading_path=list(current_heading_path),
                        metadata={
                            "google_doc_id": google_doc_id,
                            "section_index": section_index,
                            "section_heading": section_heading,
                            "start_paragraph": section_start,
                            "end_paragraph": section_end,
                            "structure_source": "google_docs_api",
                        },
                    )
                )

            current_lines = []
            section_start = None
            section_end = None
            section_heading = None

        paragraph_index = 0

        for structural_element in document.get("body", {}).get("content", []):
            paragraph = structural_element.get("paragraph")
            if not paragraph:
                continue

            paragraph_index += 1
            text = self._paragraph_text(paragraph)
            if not text:
                continue

            style = paragraph.get("paragraphStyle", {}).get("namedStyleType")
            heading_level = self._heading_level(style)

            if heading_level is not None:
                flush_section()
                heading = clean_heading(text)
                current_heading_path = current_heading_path[:heading_level - 1]
                current_heading_path.append(heading)
                current_lines = [heading]
                section_start = paragraph_index
                section_end = paragraph_index
                section_heading = heading
                continue

            if section_start is None:
                section_start = paragraph_index

            current_lines.append(text)
            section_end = paragraph_index

        flush_section()

        if not elements:
            body_text = "\n\n".join(
                self._paragraph_text(item.get("paragraph", {}))
                for item in document.get("body", {}).get("content", [])
                if item.get("paragraph")
            )
            return self._load_from_plain_text(
                google_doc_id=google_doc_id,
                document_id=document_id,
                file_name=title,
            ) if not body_text.strip() else [
                ParsedElement(
                    document_id=document_id,
                    source_type=self.source_type,
                    file_name=title,
                    element_type="section",
                    text=section.text,
                    heading_path=section.heading_path,
                    metadata={
                        "google_doc_id": google_doc_id,
                        "section_index": section_index,
                        "section_heading": (
                            section.heading_path[-1]
                            if section.heading_path else None
                        ),
                        "start_line": section.start_line,
                        "end_line": section.end_line,
                        "structure_source": "google_docs_api_plain_text",
                    },
                )
                for section_index, section in enumerate(
                    split_text_into_sections(body_text)
                )
            ]

        return elements
