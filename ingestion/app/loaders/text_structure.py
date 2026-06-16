import re
from dataclasses import dataclass, field


COMMON_SECTION_HEADINGS = {
    "academic achievements",
    "achievements",
    "certifications",
    "contact",
    "education",
    "experience",
    "extracurricular",
    "extra curricular",
    "honors",
    "interests",
    "internships",
    "leadership",
    "objective",
    "positions of responsibility",
    "projects",
    "publications",
    "research",
    "skills",
    "summary",
    "technical skills",
    "work experience",
}


@dataclass
class TextSection:
    text: str
    heading_path: list[str] = field(default_factory=list)
    start_line: int | None = None
    end_line: int | None = None


def clean_heading(line: str) -> str:
    heading = re.sub(r"^#{1,6}\s*", "", line.strip())
    heading = re.sub(r"^\d+(?:\.\d+)*[.)]\s*", "", heading)
    heading = heading.strip(" :-\t")
    return re.sub(r"\s+", " ", heading)


def is_probable_heading(line: str) -> bool:
    stripped = line.strip()

    if not stripped:
        return False

    word_count = len(stripped.split())
    normalized = clean_heading(stripped).lower()

    if len(stripped) > 100 or word_count > 12:
        return False

    if normalized in COMMON_SECTION_HEADINGS:
        return True

    if re.match(r"^#{1,6}\s+\S", stripped):
        return True

    if re.match(r"^\d+(?:\.\d+)*[.)]\s+\S", stripped) and word_count <= 10:
        return True

    if stripped.endswith(":") and word_count <= 10 and not any(char.isdigit() for char in stripped):
        return True

    has_alpha = any(char.isalpha() for char in stripped)
    has_digit = any(char.isdigit() for char in stripped)
    alpha_chars = [char for char in stripped if char.isalpha()]
    all_alpha_is_upper = alpha_chars and all(char.isupper() for char in alpha_chars)

    if (
        has_alpha
        and all_alpha_is_upper
        and not has_digit
        and ":" not in stripped
        and word_count <= 10
    ):
        return True

    return False


def split_text_into_sections(text: str, default_heading: str | None = None) -> list[TextSection]:
    sections: list[TextSection] = []
    current_heading = clean_heading(default_heading) if default_heading else None
    current_lines: list[str] = []
    start_line: int | None = None
    last_content_line: int | None = None

    def flush_section() -> None:
        nonlocal current_lines, start_line, last_content_line

        while current_lines and not current_lines[0].strip():
            current_lines.pop(0)

        while current_lines and not current_lines[-1].strip():
            current_lines.pop()

        section_text = "\n".join(current_lines).strip()
        if section_text:
            sections.append(
                TextSection(
                    text=section_text,
                    heading_path=[current_heading] if current_heading else [],
                    start_line=start_line,
                    end_line=last_content_line,
                )
            )

        current_lines = []
        start_line = None
        last_content_line = None

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()

        if not line:
            if current_lines and current_lines[-1] != "":
                current_lines.append("")
            continue

        if is_probable_heading(line):
            flush_section()
            current_heading = clean_heading(line)
            current_lines = [current_heading]
            start_line = line_number
            last_content_line = line_number
            continue

        if start_line is None:
            start_line = line_number

        current_lines.append(line)
        last_content_line = line_number

    flush_section()

    return sections
