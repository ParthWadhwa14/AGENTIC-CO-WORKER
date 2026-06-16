import json
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.llm import invoke_with_fallback
from app.agent.prompts import (
    ACTION_PROPOSAL_PROMPT,
    ANSWER_PROMPT,
    FORMATTER_PROMPT,
    PLANNER_PROMPT,
    RETRIEVAL_RELEVANCE_PROMPT,
    ROUTER_PROMPT,
)
from app.agent.schemas import ActionPlan, ActionProposal, RouteDecision
from app.agent.state import AgentState, ProposedAction, RetrievedChunk
from app.config import settings
from app.connectors.google_drive import GOOGLE_DOC_MIME_TYPE, GOOGLE_SHEET_MIME_TYPE
from app.connectors.google_sheets import GoogleSheetsConnector
from app.services.action_executor import ActionGuardrailError, validate_action
from app.services.rate_limiter import RateLimitError, check_rate_limit
from app.services.tokens import GOOGLE_DRIVE_PROVIDER, GoogleCredentialStore
from app.services.web_search import serper_search
from app.storage.metadata_store import MetadataStore
from app.sync.drive_sync import DriveSyncService
from app.sync.gmail_sync import GmailSyncService
from app.tools.retrieval_tools import DEFAULT_SOURCE_TYPES, RetrievalTools


WRITE_INTENTS = {
    "gmail_draft": "create_gmail_draft",
    "gmail_send": "send_gmail",
    "docs_create": "create_google_doc",
    "docs_update": "update_google_doc",
    "sheets_create": "create_google_sheet",
    "sheets_update": "update_google_sheet",
}
LIVE_GMAIL_PREFIX = "gmail-live:"
LIVE_GMAIL_LIMIT = 5
MIN_STRONG_CONTEXT_CHUNKS = 3
GOOGLE_DISCOVERY_LIMIT = 5
RESUME_TERMS = {"cv", "cvs", "resume", "resumes", "résumé", "curriculum vitae"}
ATTACHMENT_TERMS = {"attach", "attachment", "attached", "resume", "cv", "résumé"}
WEB_REQUIRED_TERMS = {
    "today",
    "latest",
    "recent",
    "current",
    "news",
    "market",
    "trend",
    "web",
    "internet",
    "online",
    "search the web",
    "look up",
}


def _recent_history(history: list[dict[str, str]], max_turns: int = 8) -> str:
    lines = []
    for message in history[-max_turns:]:
        role = message.get("role", "user")
        content = (message.get("content") or "").strip()
        if not content:
            continue
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _history_aware_query(state: AgentState) -> str:
    history = _recent_history(state.conversation_history, max_turns=6)
    if not history:
        return state.query

    query = state.query.strip()
    lower_query = query.lower()
    follow_up_terms = {
        "it",
        "its",
        "that",
        "this",
        "they",
        "them",
        "those",
        "these",
        "he",
        "she",
        "his",
        "her",
        "their",
        "also",
        "more",
        "same",
    }
    words = {word.strip(".,?!").lower() for word in query.split()}
    is_follow_up = (
        len(query.split()) <= 10
        or bool(words & follow_up_terms)
        or lower_query.startswith(("what about", "tell me more", "and "))
    )
    if not is_follow_up:
        return query

    return f"{history}\nCurrent question: {query}"


def _profile_context(state: AgentState) -> str:
    profile = state.agent_profile or {}
    return "\n".join(
        [
            "Agent profile:",
            profile.get("agent_description") or "",
            "",
            "User/work context:",
            profile.get("user_context") or "",
            "",
            "Response preferences:",
            profile.get("response_preferences") or "",
        ]
    ).strip()


def _runtime_context(state: AgentState) -> str:
    context = state.runtime_context or {}
    return "\n".join(
        [
            "Runtime context:",
            f"- Current date: {context.get('current_date') or 'unknown'}",
            f"- Current datetime: {context.get('current_datetime') or 'unknown'}",
            f"- Timezone: {context.get('timezone') or 'unknown'}",
            f"- Default region: {context.get('default_region') or 'India'}",
            "- Unless the user specifies another location, interpret regional questions with the default region.",
        ]
    )


def _web_context(state: AgentState) -> str:
    if not state.web_results:
        return "No web search context used."
    return "\n\n".join(
        f"[web-{index}] {result.get('title') or 'Web result'}\n"
        f"URL: {result.get('link')}\n"
        f"Snippet: {result.get('snippet')}"
        for index, result in enumerate(state.web_results, start=1)
    )


def _web_references(state: AgentState, offset: int = 0) -> list[dict]:
    return _web_references_from_results(state.web_results, offset=offset)


def _web_references_from_results(
    web_results: list[dict[str, object]],
    offset: int = 0,
) -> list[dict]:
    return [
        {
            "ref": offset + index,
            "title": result.get("title") or result.get("link") or "Web result",
            "file_name": result.get("title") or result.get("link") or "Web result",
            "open_url": result.get("link"),
            "source_type": "web",
            "metadata": {
                "snippet": result.get("snippet"),
                "date": result.get("date"),
            },
        }
        for index, result in enumerate(web_results, start=1)
        if result.get("link")
    ]


def _tokenize_text(value: str) -> set[str]:
    import re

    return {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9_-]*", value.lower())
        if len(token) > 2
    }


def _query_terms(state: AgentState) -> set[str]:
    query = state.query.lower()
    terms = _tokenize_text(query)
    if any(term in query for term in RESUME_TERMS):
        terms.update({"cv", "resume", "parth", "wadhwa"})
    return terms


def _query_wants_attachment(state: AgentState) -> bool:
    query = state.query.lower()
    return any(term in query for term in ATTACHMENT_TERMS)


def _query_wants_resume(state: AgentState) -> bool:
    query = state.query.lower()
    return any(term in query for term in RESUME_TERMS)


def _allow_web_expansion(state: AgentState) -> bool:
    if not state.allow_web_search:
        return False
    query = state.query.lower()
    if state.needs_write_action and not any(term in query for term in WEB_REQUIRED_TERMS):
        return False
    if _query_wants_attachment(state) or _query_wants_resume(state):
        return False
    return any(term in query for term in WEB_REQUIRED_TERMS)


def _lexically_relevant_chunk(chunk: RetrievedChunk, state: AgentState) -> bool:
    if chunk.metadata.get("live_google_discovery"):
        return True
    if chunk.document_id in set(state.priority_document_ids + state.pinned_document_ids):
        return True
    query_terms = _query_terms(state)
    haystack = " ".join(
        [
            chunk.title or "",
            chunk.file_name or "",
            chunk.source_type or "",
            str(chunk.metadata.get("mime_type") or ""),
            chunk.text[:1200],
        ]
    )
    haystack_terms = _tokenize_text(haystack)
    if _query_wants_resume(state):
        name = f"{chunk.title or ''} {chunk.file_name or ''}".lower()
        if any(term in name for term in ["cv", "resume", "parth", "wadhwa"]):
            return True
    if chunk.score is not None and chunk.score >= 0.58:
        return True
    return bool(query_terms & haystack_terms)


def _lexically_relevant_web(result: dict[str, object], state: AgentState) -> bool:
    if not _allow_web_expansion(state):
        return False
    query_terms = _query_terms(state)
    haystack = " ".join(
        str(result.get(key) or "") for key in ["title", "snippet", "link"]
    )
    return bool(query_terms & _tokenize_text(haystack))


def _filter_relevant_context(
    state: AgentState,
    chunks: list[RetrievedChunk],
    web_results: list[dict[str, object]],
) -> tuple[list[RetrievedChunk], list[dict[str, object]], str]:
    candidates: list[tuple[str, int, str]] = []
    for index, chunk in enumerate(chunks, start=1):
        candidates.append(
            (
                "chunk",
                index - 1,
                "\n".join(
                    [
                        f"Index: {len(candidates) + 1}",
                        f"Type: {chunk.source_type}",
                        f"Title: {chunk.title or chunk.file_name or ''}",
                        f"Score: {chunk.score if chunk.score is not None else 'n/a'}",
                        f"Text: {chunk.text[:900]}",
                    ]
                ),
            )
        )
    for index, result in enumerate(web_results, start=1):
        candidates.append(
            (
                "web",
                index - 1,
                "\n".join(
                    [
                        f"Index: {len(candidates) + 1}",
                        "Type: web",
                        f"Title: {result.get('title') or ''}",
                        f"URL: {result.get('link') or ''}",
                        f"Snippet: {result.get('snippet') or ''}",
                    ]
                ),
            )
        )

    if not candidates:
        return chunks, web_results, "relevance skipped empty"

    fallback_chunk_indexes = {
        index
        for index, chunk in enumerate(chunks)
        if _lexically_relevant_chunk(chunk, state)
    }
    fallback_web_indexes = {
        index
        for index, result in enumerate(web_results)
        if _lexically_relevant_web(result, state)
    }

    prompt = {
        "user_query": state.query,
        "intent": state.intent,
        "needs_write_action": state.needs_write_action,
        "items": [candidate[2] for candidate in candidates],
    }
    try:
        raw = invoke_with_fallback(
            [
                SystemMessage(content=RETRIEVAL_RELEVANCE_PROMPT),
                HumanMessage(content=json.dumps(prompt)),
            ]
        )
        parsed = json.loads(raw)
        relevant_item_numbers = {
            int(item.get("index"))
            for item in parsed.get("items", [])
            if item.get("relevant") is True and item.get("index") is not None
        }
        keep_chunks: list[RetrievedChunk] = []
        keep_web: list[dict[str, object]] = []
        for item_number, (kind, original_index, _) in enumerate(candidates, start=1):
            if item_number not in relevant_item_numbers:
                continue
            if kind == "chunk":
                keep_chunks.append(chunks[original_index])
            else:
                keep_web.append(web_results[original_index])
        if keep_chunks or keep_web:
            return (
                keep_chunks,
                keep_web,
                f"llm relevance kept chunks={len(keep_chunks)} web={len(keep_web)}",
            )
    except Exception:
        pass

    keep_chunks = [chunk for index, chunk in enumerate(chunks) if index in fallback_chunk_indexes]
    keep_web = [result for index, result in enumerate(web_results) if index in fallback_web_indexes]
    if keep_chunks or keep_web:
        return (
            keep_chunks,
            keep_web,
            f"fallback relevance kept chunks={len(keep_chunks)} web={len(keep_web)}",
        )
    return [], [], "relevance dropped all weak candidates"


def _unique_strings(values: list[str]) -> list[str]:
    seen = set()
    unique = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            unique.append(value)
    return unique


def _merge_chunks(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    merged: list[RetrievedChunk] = []
    seen = set()
    for chunk in chunks:
        key = chunk.chunk_id or f"{chunk.document_id}:{chunk.text[:80]}"
        if key in seen:
            continue
        seen.add(key)
        merged.append(chunk)
    return merged


def _references_from_chunks(chunks: list[RetrievedChunk]) -> list[dict]:
    references = []
    for index, chunk in enumerate(chunks, start=1):
        reference = dict(chunk.reference or {})
        if not reference:
            reference = {
                "document_id": chunk.document_id,
                "chunk_id": chunk.chunk_id,
                "source_type": chunk.source_type,
                "title": chunk.title or chunk.file_name or chunk.source_type,
                "file_name": chunk.file_name or chunk.title or chunk.source_type,
                "open_url": None,
                "metadata": chunk.metadata,
            }
        reference["ref"] = index
        references.append(reference)
    return references


def _is_context_weak(chunks: list[RetrievedChunk], state: AgentState) -> bool:
    if len(chunks) >= min(MIN_STRONG_CONTEXT_CHUNKS, state.limit):
        return False
    if any((chunk.score or 0) >= 0.6 for chunk in chunks):
        return False
    return True


def _google_discovery_query(query: str) -> str:
    import re

    cleaned = query.strip()
    match = re.search(
        r"(?:named|name|called|titled)\s+[\"']?(.+?)(?:[\"']?\s+(?:in|on|from|inside|under)\b|[\"']?$)",
        cleaned,
        flags=re.IGNORECASE,
    )
    if match:
        return match.group(1).strip(" .\"'")

    for phrase in [
        "please find",
        "find",
        "search for",
        "look for",
        "sheet",
        "sheets",
        "doc",
        "docs",
        "document",
        "drive",
        "gmail",
        "email",
    ]:
        cleaned = cleaned.replace(phrase, " ")
        cleaned = cleaned.replace(phrase.title(), " ")
    return " ".join(cleaned.split()) or query.strip()


def _google_discovery_queries(query: str) -> list[str]:
    base = _google_discovery_query(query)
    lowered = query.lower()
    queries = [base]
    if any(term in lowered for term in ["cv", "cvs", "cv's", "resume", "résumé"]):
        queries.extend(["cv", "resume", "résumé", "curriculum vitae"])
    if any(term in lowered for term in ["spreadsheet", "sheet", "sheets"]):
        queries.append(base.replace("spreadsheet", "").replace("sheet", "").strip())
    if any(term in lowered for term in ["doc", "docs", "document"]):
        queries.append(base.replace("document", "").replace("doc", "").strip())
    return _unique_strings([item.strip(" .\"'") for item in queries if item.strip()])


def _needs_live_google_discovery(state: AgentState) -> bool:
    query = state.query.lower()
    google_terms = {
        "drive",
        "doc",
        "docs",
        "document",
        "sheet",
        "sheets",
        "spreadsheet",
        "gmail",
        "email",
        "mail",
        "link",
        "links",
        "cv",
        "resume",
    }
    search_terms = {"find", "search", "look for", "named", "called", "where is"}
    return (
        bool(set(state.sources_needed) & {"gmail", "google_doc", "google_sheet"})
        or any(term in query for term in google_terms)
        or any(term in query for term in search_terms)
    )


def _drive_file_chunk(file: dict, source_type: str, index: int) -> RetrievedChunk:
    title = file.get("name") or file.get("id") or "Google file"
    metadata = {
        "google_file_id": file.get("id"),
        "mime_type": file.get("mimeType"),
        "modified_time": file.get("modifiedTime"),
        "live_google_discovery": True,
    }
    reference = {
        "ref": index,
        "document_id": None,
        "chunk_id": file.get("id"),
        "source_type": source_type,
        "title": title,
        "file_name": title,
        "open_url": file.get("webViewLink"),
        "metadata": metadata,
    }
    return RetrievedChunk(
        chunk_id=file.get("id"),
        document_id=None,
        source_type=source_type,
        file_name=title,
        title=title,
        text=(
            f"Live Google {source_type} discovery result\n"
            f"Name: {title}\n"
            f"URL: {file.get('webViewLink') or ''}\n"
            f"Modified: {file.get('modifiedTime') or 'unknown'}\n"
            f"Mime type: {file.get('mimeType') or 'unknown'}"
        ),
        score=None,
        metadata=metadata,
        reference=reference,
    )


def _live_google_workspace_discover(state: AgentState) -> list[RetrievedChunk]:
    chunks: list[RetrievedChunk] = []

    try:
        check_rate_limit(
            f"live_google_discovery:{state.user_id}",
            max_calls=10,
            window_seconds=60,
        )
    except RateLimitError:
        return chunks

    query_lower = state.query.lower()
    source_targets: list[tuple[str, str | None]] = []
    if any(term in query_lower for term in ["sheet", "sheets", "spreadsheet"]):
        source_targets.append(("google_sheet", GOOGLE_SHEET_MIME_TYPE))
    if any(term in query_lower for term in ["doc", "docs", "document"]):
        source_targets.append(("google_doc", GOOGLE_DOC_MIME_TYPE))
    if any(
        term in query_lower
        for term in ["drive", "file", "folder", "link", "links", "cv", "resume"]
    ):
        source_targets.append(("google_drive", None))
    if not source_targets:
        source_targets.extend(
            [
                ("google_sheet", GOOGLE_SHEET_MIME_TYPE),
                ("google_doc", GOOGLE_DOC_MIME_TYPE),
                ("google_drive", None),
            ]
        )

    try:
        drive = DriveSyncService(user_id=state.user_id)
        seen_file_ids = set()
        for source_type, mime_type in source_targets:
            for search_query in _google_discovery_queries(state.query):
                result = drive.drive.discover_files(
                    query=search_query,
                    mime_type=mime_type,
                    page_size=GOOGLE_DISCOVERY_LIMIT,
                )
                for file in result.get("files", []):
                    file_id = file.get("id")
                    if file_id in seen_file_ids or not drive.is_supported(file):
                        continue
                    seen_file_ids.add(file_id)
                    chunks.append(
                        _drive_file_chunk(
                            file,
                            source_type=source_type,
                            index=len(chunks) + 1,
                        )
                    )
    except Exception:
        pass

    if any(term in query_lower for term in ["gmail", "email", "mail"]):
        gmail_state = state.model_copy()
        gmail_state.query = _safe_gmail_query(_google_discovery_query(state.query))
        gmail_chunks, _ = _live_gmail_retrieve(gmail_state)
        chunks.extend(gmail_chunks)

    return chunks[:GOOGLE_DISCOVERY_LIMIT]


def _target_name_from_query(query: str) -> str:
    import re

    patterns = [
        r"(?:fill|update|edit|append|write\s+to)\s+(?:the\s+)?[\"']([^\"']+)[\"']\s+(?:spreadsheet|sheet|file|doc|document)\b",
        r"(?:spreadsheet|sheet|file|doc|document)\s+(?:named|name|called|titled)\s+[\"']([^\"']+)[\"']",
        r"(?:named|name|called|titled)\s+[\"']([^\"']+)[\"']",
        r"(?:spreadsheet|sheet|file|doc|document)\s+(?:named|name|called|titled)\s+[\"']?([^\"']+?)(?:[\"']?\s+(?:with|and|in|from|to)\b|[\"']?$)",
        r"(?:named|name|called|titled)\s+[\"']?([^\"']+?)(?:[\"']?\s+(?:spreadsheet|sheet|file|doc|document|with|and|in|from|to)\b|[\"']?$)",
        r"(?:fill|update|edit|append|write\s+to)\s+[\"']?([^\"']+?)[\"']?\s+(?:spreadsheet|sheet|file|doc|document)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, query, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip(" .\"'")
    return _google_discovery_query(query)


def _chunk_matches_target(chunk: RetrievedChunk, target_name: str) -> bool:
    if not target_name:
        return True
    target = target_name.lower()
    names = [
        chunk.title or "",
        chunk.file_name or "",
        str(chunk.metadata.get("name") or ""),
    ]
    return any(target in name.lower() or name.lower() in target for name in names)


def _resolve_google_file_id_from_chunks(
    chunks: list[RetrievedChunk],
    source_type: str,
    target_name: str,
) -> str | None:
    candidates = [
        chunk
        for chunk in chunks
        if chunk.source_type == source_type and _chunk_matches_target(chunk, target_name)
    ]
    if not candidates:
        candidates = [chunk for chunk in chunks if chunk.source_type == source_type]
    for chunk in candidates:
        file_id = (
            chunk.metadata.get("google_file_id")
            or chunk.metadata.get("spreadsheet_id")
            or chunk.metadata.get("document_id")
            or chunk.chunk_id
        )
        if file_id:
            return str(file_id)
    return None


def _action_memories(history: list[dict[str, str]]) -> list[dict]:
    import re

    memories = []
    pattern = re.compile(r"```json action-memory\s*(.*?)```", re.DOTALL)
    for message in history:
        content = message.get("content") or ""
        for match in pattern.findall(content):
            try:
                parsed = json.loads(match.strip())
            except Exception:
                continue
            if isinstance(parsed, dict):
                memories.append(parsed)
    return memories


def _latest_action_memory(
    state: AgentState,
    action_type: str | None = None,
) -> dict | None:
    memories = _action_memories(state.conversation_history)
    for memory in reversed(memories):
        if action_type is None or memory.get("action_type") == action_type:
            return memory
    return None


def _spreadsheet_id_from_history(history: list[dict[str, str]]) -> str | None:
    import re

    patterns = [
        r"spreadsheet\s+ID:\s*([A-Za-z0-9_-]{20,})",
        r"\bID:\s*([A-Za-z0-9_-]{20,})",
        r"spreadsheet_id[\"'`\s:]+([A-Za-z0-9_-]{20,})",
        r"docs\.google\.com/spreadsheets/d/([A-Za-z0-9_-]+)",
    ]
    for message in reversed(history):
        content = message.get("content") or ""
        for pattern in patterns:
            match = re.search(pattern, content, flags=re.IGNORECASE)
            if match:
                return match.group(1)
    return None


def _doc_artifacts(state: AgentState) -> list[dict]:
    artifacts = []
    for memory in _action_memories(state.conversation_history):
        if memory.get("action_type") != "create_google_doc":
            continue
        payload = memory.get("payload") or {}
        result = memory.get("result") or {}
        document_id = result.get("documentId") or result.get("document_id")
        document_url = (
            result.get("documentUrl")
            or result.get("document_url")
            or (
                f"https://docs.google.com/document/d/{document_id}/edit"
                if document_id else None
            )
        )
        artifacts.append(
            {
                "title": payload.get("title") or result.get("title") or "",
                "document_id": document_id,
                "document_url": document_url,
            }
        )

    for chunk in state.retrieved_chunks:
        if chunk.source_type != "google_doc":
            continue
        url = (chunk.reference or {}).get("open_url") or chunk.metadata.get("web_url")
        document_id = chunk.metadata.get("google_file_id") or chunk.chunk_id
        if not url and document_id:
            url = f"https://docs.google.com/document/d/{document_id}/edit"
        artifacts.append(
            {
                "title": chunk.title or chunk.file_name or "",
                "document_id": document_id,
                "document_url": url,
            }
        )
    return artifacts


def _best_doc_url(state: AgentState, target_name: str = "") -> str | None:
    artifacts = _doc_artifacts(state)
    if target_name:
        for artifact in reversed(artifacts):
            title = (artifact.get("title") or "").lower()
            if target_name.lower() in title or title in target_name.lower():
                return artifact.get("document_url")
    for artifact in reversed(artifacts):
        if artifact.get("document_url"):
            return artifact["document_url"]
    return None


def _uploaded_attachment_candidates(state: AgentState) -> list[dict]:
    documents = MetadataStore().list_documents(state.user_id, limit=200)
    wants_cv = _query_wants_resume(state)
    candidates: list[tuple[int, dict]] = []
    for document in documents:
        if document.get("source") != "upload":
            continue
        local_path = _existing_local_path_for_document(document)
        if not local_path:
            continue
        name = (document.get("file_name") or "").lower()
        mime_type = document.get("mime_type") or "application/octet-stream"
        is_pdf_or_doc = (
            mime_type in {
                "application/pdf",
                "application/msword",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            }
            or name.endswith((".pdf", ".doc", ".docx"))
        )
        if wants_cv and not any(term in name for term in ["cv", "resume", "parth", "wadhwa"]):
            continue
        score = 0
        if is_pdf_or_doc:
            score += 4
        if "resume" in name or "cv" in name:
            score += 4
        if "parth" in name:
            score += 2
        if "wadhwa" in name:
            score += 2
        if document.get("index_status") == "indexed":
            score += 1
        candidates.append((
            score,
            {
                "document_id": document.get("id"),
                "local_path": local_path,
                "filename": document.get("file_name"),
                "mime_type": mime_type,
            },
        ))
    candidates.sort(key=lambda item: item[0], reverse=True)
    return [candidate for _, candidate in candidates]


def _existing_local_path_for_document(document: dict) -> str | None:
    local_path = document.get("local_path")
    if local_path and Path(local_path).is_file():
        return str(Path(local_path))

    document_id = document.get("id")
    file_name = document.get("file_name")
    if document_id and file_name:
        candidate = settings.UPLOAD_DIR / f"{document_id}_{file_name}"
        if candidate.is_file():
            return str(candidate)
    return None


def _valid_local_attachments(attachments: object) -> list[dict]:
    if not isinstance(attachments, list):
        return []
    valid = []
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        local_path = attachment.get("local_path")
        if not isinstance(local_path, str) or not local_path.strip():
            continue
        path = Path(local_path)
        if not path.is_file():
            continue
        valid.append(
            {
                "document_id": attachment.get("document_id"),
                "local_path": str(path),
                "filename": attachment.get("filename") or path.name,
                "mime_type": attachment.get("mime_type") or "application/octet-stream",
            }
        )
    return valid


def _column_label(index: int) -> str:
    label = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        label = chr(65 + remainder) + label
    return label


def _sheet_range(sheet_title: str, row: int) -> str:
    escaped = sheet_title.replace("'", "''")
    return f"'{escaped}'!A{row}"


def _random_value_for_header(header: str, row_index: int) -> str:
    normalized = header.lower()
    names = ["Aarav Mehta", "Diya Sharma", "Kabir Rao", "Ananya Gupta", "Vivaan Singh"]
    cities = ["Delhi", "Mumbai", "Bengaluru", "Pune", "Jaipur"]
    colleges = ["IIT Delhi", "BITS Pilani", "VIT Vellore", "SRM University", "Manipal University"]
    emails = ["student{n}@example.com", "learner{n}@example.com"]
    if "name" in normalized:
        return names[row_index % len(names)]
    if "city" in normalized or "location" in normalized:
        return cities[row_index % len(cities)]
    if "college" in normalized or "university" in normalized or "school" in normalized:
        return colleges[row_index % len(colleges)]
    if "email" in normalized or "mail" in normalized:
        return emails[row_index % len(emails)].format(n=row_index + 1)
    if "phone" in normalized or "mobile" in normalized:
        return f"98765{row_index + 10000:05d}"[-10:]
    if "age" in normalized:
        return str(18 + (row_index % 10))
    if "date" in normalized:
        return f"2026-06-{(row_index % 28) + 1:02d}"
    if "id" in normalized:
        return f"ID-{row_index + 1:03d}"
    if "score" in normalized or "marks" in normalized:
        return str(60 + (row_index * 3) % 40)
    return f"{header.strip() or 'Value'} {row_index + 1}"


def _fill_sheet_payload_from_headers(state: AgentState, payload: dict) -> dict:
    spreadsheet_id = payload.get("spreadsheet_id")
    query = state.query.lower()
    if not spreadsheet_id or (
        payload.get("range") and payload.get("values")
    ):
        return payload
    if not any(term in query for term in ["random", "20", "entries", "rows", "columns"]):
        return payload

    try:
        credentials = GoogleCredentialStore().get_credentials(
            state.user_id,
            provider=GOOGLE_DRIVE_PROVIDER,
        )
        sheets = GoogleSheetsConnector(credentials)
        metadata = sheets.get_spreadsheet(spreadsheet_id)
        first_sheet = (metadata.get("sheets") or [{}])[0]
        sheet_title = first_sheet.get("properties", {}).get("title") or "Sheet1"
        header_values = sheets.get_values(spreadsheet_id, f"'{sheet_title}'!1:1")
        headers = header_values[0] if header_values else ["Name", "City", "College"]
    except Exception:
        sheet_title = "Sheet1"
        headers = ["Name", "City", "College"]

    payload["range"] = payload.get("range") or _sheet_range(sheet_title, 2)
    payload["operation"] = payload.get("operation") or "update_values"
    payload["values"] = [
        [_random_value_for_header(str(header), row_index) for header in headers]
        for row_index in range(20)
    ]
    return payload


def _compose_doc_text_from_context(state: AgentState) -> str:
    content_chunks = [
        chunk
        for chunk in state.retrieved_chunks
        if not chunk.metadata.get("live_google_discovery")
        and chunk.text.strip()
    ][:8]
    if not content_chunks:
        return ""

    source_text = "\n\n---\n\n".join(
        f"Source: {chunk.title or chunk.file_name or chunk.source_type}\n"
        f"{chunk.text[:4000]}"
        for chunk in content_chunks
    )
    prompt = (
        "Create polished Google Doc body text from the retrieved source content. "
        "Use clear headings, preserve truthful CV facts, remove duplicate fragments, "
        "and do not invent missing details. Return only the document body text.\n\n"
        f"User request: {state.query}\n\nRetrieved content:\n{source_text}"
    )
    try:
        return invoke_with_fallback(
            [
                SystemMessage(content="You draft concise, well-structured document text."),
                HumanMessage(content=prompt),
            ]
        )[:50000].strip()
    except Exception:
        return source_text[:50000].strip()


def _resolve_action_payload(state: AgentState, action_payload: dict) -> dict:
    payload = dict(action_payload.get("payload") or {})
    action_type = action_payload.get("action_type")
    target_name = _target_name_from_query(state.query)
    wants_attachment = _query_wants_attachment(state)

    if action_type == "send_gmail" and not payload.get("draft_id"):
        draft_memory = _latest_action_memory(state, "create_gmail_draft")
        draft_result = (draft_memory or {}).get("result") or {}
        draft_id = draft_result.get("id")
        if (
            draft_id
            and not wants_attachment
            and any(term in state.query.lower() for term in ["above", "draft", "previous"])
        ):
            payload["draft_id"] = draft_id

    if action_type == "send_gmail" and wants_attachment and payload.get("draft_id"):
        draft_memory = _latest_action_memory(state, "create_gmail_draft")
        draft_payload = (draft_memory or {}).get("payload") or {}
        for key in ["to", "cc", "bcc", "subject", "body", "thread_id"]:
            if not payload.get(key) and draft_payload.get(key):
                payload[key] = draft_payload[key]
        payload.pop("draft_id", None)

    if action_type in {"create_gmail_draft", "send_gmail"}:
        doc_url = _best_doc_url(state, target_name)
        body = payload.get("body") or ""
        if doc_url and "docs.google.com/document" not in body:
            if "Google Doc" in body:
                body = body.replace("Google Doc)", f"Google Doc): {doc_url}")
            elif "resume below" in body.lower():
                body = f"{body.rstrip()}\n\nResume document: {doc_url}"
            else:
                body = f"{body.rstrip()}\n\nGoogle Doc: {doc_url}"
            payload["body"] = body

        if payload.get("attachments"):
            payload["attachments"] = _valid_local_attachments(payload.get("attachments"))

        if wants_attachment and not payload.get("attachments"):
            attachments = _uploaded_attachment_candidates(state)
            if attachments:
                payload["attachments"] = attachments[:1]
            else:
                payload["attachments_required"] = True

    if action_type == "update_google_sheet" and not payload.get("spreadsheet_id"):
        spreadsheet_id = _spreadsheet_id_from_history(state.conversation_history)
        spreadsheet_id = spreadsheet_id or _resolve_google_file_id_from_chunks(
            state.retrieved_chunks,
            "google_sheet",
            target_name,
        )
        if not spreadsheet_id:
            discovery_state = state.model_copy()
            discovery_state.query = target_name or state.query
            discovery_chunks = _live_google_workspace_discover(discovery_state)
            spreadsheet_id = _resolve_google_file_id_from_chunks(
                discovery_chunks,
                "google_sheet",
                target_name,
            )
        if spreadsheet_id:
            payload["spreadsheet_id"] = spreadsheet_id

    if action_type == "update_google_sheet":
        payload = _fill_sheet_payload_from_headers(state, payload)

    if action_type == "update_google_doc" and not payload.get("document_id"):
        document_id = _resolve_google_file_id_from_chunks(
            state.retrieved_chunks,
            "google_doc",
            target_name,
        )
        if document_id:
            payload["document_id"] = document_id

    if action_type == "create_google_doc" and not (payload.get("text") or "").strip():
        doc_text = _compose_doc_text_from_context(state)
        if doc_text:
            payload["text"] = doc_text

    if action_type == "create_google_doc" and not (payload.get("title") or "").strip():
        payload["title"] = "Consolidated CV"

    return {
        **action_payload,
        "payload": payload,
    }


def _safe_gmail_query(query: str) -> str:
    gmail_query = query.strip()
    if "-in:spam" not in gmail_query:
        gmail_query += " -in:spam"
    if "-in:trash" not in gmail_query:
        gmail_query += " -in:trash"
    if "newer_than:" not in gmail_query and "after:" not in gmail_query:
        gmail_query += " newer_than:365d"
    return gmail_query


def _gmail_reference(
    message_id: str,
    subject: str,
    index: int,
    metadata: dict | None = None,
) -> dict:
    return {
        "ref": index,
        "document_id": f"{LIVE_GMAIL_PREFIX}{message_id}",
        "chunk_id": message_id,
        "source_type": "gmail",
        "title": subject or "(no subject)",
        "file_name": subject or "(no subject)",
        "open_url": f"https://mail.google.com/mail/u/0/#all/{message_id}",
        "score": None,
        "metadata": metadata or {},
    }


def _gmail_message_chunk(
    service: GmailSyncService,
    message_id: str,
    index: int,
) -> tuple[RetrievedChunk | None, dict | None]:
    message = service.gmail.get_message_full(message_id)
    headers = service.gmail.extract_headers(message)
    body_text = service.gmail.extract_plain_text(message)
    if not body_text.strip():
        return None, None

    subject = headers.get("subject") or "(no subject)"
    metadata = {
        "gmail_message_id": message_id,
        "gmail_thread_id": message.get("threadId"),
        "from": headers.get("from"),
        "to": headers.get("to"),
        "date": headers.get("date"),
        "snippet": message.get("snippet"),
        "live_source": True,
    }
    reference = _gmail_reference(
        message_id=message_id,
        subject=subject,
        index=index,
        metadata=metadata,
    )
    chunk = RetrievedChunk(
        chunk_id=message_id,
        document_id=reference["document_id"],
        source_type="gmail",
        file_name=subject,
        title=subject,
        text=(
            f"Subject: {subject}\n"
            f"From: {headers.get('from') or ''}\n"
            f"To: {headers.get('to') or ''}\n"
            f"Date: {headers.get('date') or ''}\n\n"
            f"{body_text}"
        ),
        score=None,
        metadata=metadata,
        reference=reference,
    )
    return chunk, reference


def _live_gmail_retrieve(
    state: AgentState,
    start_ref: int = 1,
) -> tuple[list[RetrievedChunk], list[dict]]:
    try:
        check_rate_limit(
            f"live_gmail:{state.user_id}",
            max_calls=12,
            window_seconds=60,
        )
        service = GmailSyncService(user_id=state.user_id)
    except (Exception, RateLimitError) as exc:
        return [], [
            {
                "ref": start_ref,
                "title": "Gmail connection unavailable",
                "file_name": "Gmail connection unavailable",
                "source_type": "gmail",
                "open_url": None,
                "metadata": {"error": str(exc)},
            }
        ]

    live_ids = [
        document_id.removeprefix(LIVE_GMAIL_PREFIX)
        for document_id in state.pinned_document_ids
        if document_id.startswith(LIVE_GMAIL_PREFIX)
    ]
    if not live_ids:
        result = service.gmail.list_messages(
            query=_safe_gmail_query(state.query),
            max_results=LIVE_GMAIL_LIMIT,
        )
        live_ids = [message["id"] for message in result.get("messages", [])]

    chunks: list[RetrievedChunk] = []
    references: list[dict] = []
    for message_id in live_ids[:LIVE_GMAIL_LIMIT]:
        chunk, reference = _gmail_message_chunk(
            service,
            message_id=message_id,
            index=start_ref + len(references),
        )
        if chunk and reference:
            chunks.append(chunk)
            references.append(reference)

    return chunks, references


def _should_retrieve_general_query(query: str) -> bool:
    words = query.split()
    if len(words) <= 2 and query.strip().lower() in {
        "hi",
        "hello",
        "hey",
        "thanks",
        "thank you",
    }:
        return False
    return True


def _write_action_needs_context(query: str, intent: str) -> bool:
    lowered = query.lower()
    source_terms = {
        "from",
        "using",
        "based on",
        "drive",
        "doc",
        "docs",
        "sheet",
        "spreadsheet",
        "gmail",
        "email",
        "cv",
        "resume",
        "content",
        "data",
    }
    return intent in WRITE_INTENTS and any(term in lowered for term in source_terms)


def _parse_json_model(raw: str, model):
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.removeprefix("json").strip()
    return model.model_validate_json(cleaned)


def route_intent_node(state: AgentState) -> dict:
    history = _recent_history(state.conversation_history, max_turns=4)
    router_query = (
        f"Recent conversation:\n{history}\n\nCurrent query:\n{state.query}"
        if history else state.query
    )
    try:
        raw = invoke_with_fallback(
            [
                SystemMessage(content=ROUTER_PROMPT),
                HumanMessage(content=router_query),
            ]
        )
        decision = _parse_json_model(raw, RouteDecision)
    except Exception as exc:
        query = state.query.lower()
        sources = []
        intent = "document_qa"
        if any(word in query for word in ["email", "gmail", "mail", "inbox"]):
            intent = "gmail_search"
            sources = ["gmail"]
        elif any(word in query for word in ["csv", "sheet", "excel", "row", "column"]):
            intent = "table_analysis"
            sources = ["csv", "xlsx", "google_sheet"]
        decision = RouteDecision(
            intent=intent,
            sources_needed=sources,
            needs_retrieval=True,
            needs_write_action=intent in WRITE_INTENTS,
            reasoning=f"Fallback route after router error: {exc}",
        )

    if state.requested_source_type:
        decision.sources_needed = [state.requested_source_type]

    query_lower = state.query.lower()
    if (
        any(
            token in query_lower
            for token in ["add", "fill", "complete", "update", "append", "insert"]
        )
        and any(
            token in query_lower
            for token in ["row", "rows", "entry", "entries", "value", "values", "column", "columns"]
        )
        and decision.intent not in WRITE_INTENTS
    ):
        decision.intent = "sheets_update"
        decision.sources_needed = ["google_sheet"]
        decision.needs_retrieval = True
        decision.needs_write_action = True
    if any(
        token in query_lower
        for token in [
            "gmail",
            "email",
            "emails",
            "mail",
            "inbox",
            "thread",
            "sender",
            "recipient",
        ]
    ) and decision.intent not in {"gmail_draft", "gmail_send"}:
        decision.intent = "gmail_search"
        decision.sources_needed = ["gmail"]
        decision.needs_retrieval = True
    elif decision.intent not in WRITE_INTENTS and any(
        token in query_lower
        for token in [
            "sheet",
            "spreadsheet",
            "csv",
            "xlsx",
            "table",
            "row",
            "column",
            "analytics",
            "dataset",
        ]
    ):
        decision.intent = "table_analysis"
        decision.sources_needed = ["csv", "xlsx", "google_sheet"]
        decision.needs_retrieval = True
    elif any(
        token in query_lower
        for token in ["drive", "doc", "docs", "document", "pdf", "file"]
    ) and decision.intent not in WRITE_INTENTS:
        decision.intent = "document_qa"
        decision.sources_needed = ["pdf", "txt", "pptx", "google_doc"]
        decision.needs_retrieval = True

    needs_retrieval = decision.needs_retrieval
    if decision.intent == "sheets_update":
        decision.sources_needed = ["google_sheet"]
        needs_retrieval = True
    elif decision.intent == "docs_update":
        decision.sources_needed = ["google_doc"]
        needs_retrieval = True
    elif decision.intent == "docs_create" and _write_action_needs_context(
        state.query,
        decision.intent,
    ):
        decision.sources_needed = ["pdf", "txt", "google_doc"]
        needs_retrieval = True
    elif _write_action_needs_context(state.query, decision.intent):
        needs_retrieval = True

    if decision.intent == "general_chat":
        needs_retrieval = _should_retrieve_general_query(state.query)
    if (
        decision.intent in WRITE_INTENTS
        and not decision.sources_needed
        and not _write_action_needs_context(state.query, decision.intent)
    ):
        needs_retrieval = False

    return {
        "intent": decision.intent,
        "sources_needed": decision.sources_needed,
        "needs_retrieval": needs_retrieval,
        "needs_write_action": decision.needs_write_action,
        "trace": state.trace + [
            f"route intent={decision.intent} sources={decision.sources_needed}"
        ],
    }


def plan_node(state: AgentState) -> dict:
    planner_input = {
        "query": state.query,
        "intent": state.intent,
        "sources_needed": state.sources_needed,
        "needs_write_action": state.needs_write_action,
    }
    try:
        raw = invoke_with_fallback(
            [
                SystemMessage(content=PLANNER_PROMPT),
                HumanMessage(content=json.dumps(planner_input)),
            ]
        )
        plan = _parse_json_model(raw, ActionPlan)
    except Exception:
        plan = ActionPlan(
            steps=[
                "Retrieve relevant workspace context.",
                "Answer using retrieved evidence.",
                "Format the response with clickable source links returned separately.",
            ],
            needs_approval=state.intent in WRITE_INTENTS,
            action_type=WRITE_INTENTS.get(state.intent, "none"),
        )

    return {
        "plan": plan.steps,
        "approval_status": "pending" if plan.needs_approval else "not_required",
        "trace": state.trace + [f"plan steps={len(plan.steps)}"],
    }


def retrieve_node(state: AgentState) -> dict:
    if not state.needs_retrieval:
        return {
            "references": _web_references(state),
            "trace": state.trace + ["retrieval skipped"],
        }

    priority_document_ids = _unique_strings(
        state.priority_document_ids + state.pinned_document_ids
    )
    live_priority_ids = [
        document_id
        for document_id in priority_document_ids
        if document_id.startswith(LIVE_GMAIL_PREFIX)
    ]
    non_live_priority_ids = [
        document_id
        for document_id in priority_document_ids
        if not document_id.startswith(LIVE_GMAIL_PREFIX)
    ]
    source_types = state.sources_needed or DEFAULT_SOURCE_TYPES
    if state.intent == "gmail_search":
        source_types = ["gmail"]
    elif state.intent == "table_analysis":
        source_types = ["csv", "xlsx", "google_sheet"]
    elif state.requested_source_type:
        source_types = [state.requested_source_type]

    google_discovery_needed = _needs_live_google_discovery(state)
    live_google_chunks = (
        _live_google_workspace_discover(state) if google_discovery_needed else []
    )

    live_chunks: list[RetrievedChunk] = []
    if live_priority_ids:
        live_chunks, _ = _live_gmail_retrieve(state)
    elif state.intent == "gmail_search":
        live_chunks, _ = _live_gmail_retrieve(state)

    search_query = _history_aware_query(state)
    workspace_chunks: list[RetrievedChunk] = []
    errors = list(state.errors)
    fallback_to_default = not (
        google_discovery_needed
        or state.intent == "table_analysis"
        or state.requested_source_type
    )
    try:
        workspace_chunks, _ = RetrievalTools().search_workspace(
            query=search_query,
            source_types=source_types,
            limit=state.limit,
            priority_document_ids=non_live_priority_ids,
            fallback_to_default=fallback_to_default,
        )
    except Exception as exc:
        errors.append(str(exc))

    chunks = _merge_chunks(live_google_chunks + live_chunks + workspace_chunks)
    web_results = list(state.web_results)
    trace = state.trace + [
        (
            "retrieval attempt 1 "
            f"priority={len(non_live_priority_ids) + len(live_priority_ids)} "
            f"live_google={len(live_google_chunks)} chunks={len(chunks)}"
        )
    ]

    should_expand = (
        _is_context_weak(chunks, state)
        and state.retrieval_attempts + 1 < state.max_retrieval_attempts
        and not state.requested_source_type
    )
    if should_expand:
        expanded_chunks: list[RetrievedChunk] = []
        if not google_discovery_needed:
            try:
                expanded_chunks, _ = RetrievalTools().search_workspace(
                    query=search_query,
                    source_types=DEFAULT_SOURCE_TYPES,
                    limit=state.limit,
                    priority_document_ids=non_live_priority_ids,
                )
            except Exception as exc:
                errors.append(str(exc))

        if (
            state.intent != "gmail_search"
            and not live_priority_ids
            and not google_discovery_needed
        ):
            more_live_chunks, _ = _live_gmail_retrieve(state)
            expanded_chunks = more_live_chunks + expanded_chunks

        if _allow_web_expansion(state) and not web_results:
            try:
                web_results = serper_search(search_query)
            except Exception as exc:
                errors.append(f"web_search: {exc}")

        chunks = _merge_chunks(chunks + expanded_chunks)[: state.limit]
        trace.append(
            "retrieval attempt 2 expanded to workspace/gmail/web "
            f"chunks={len(chunks)} web_results={len(web_results)}"
        )

    chunks, web_results, relevance_trace = _filter_relevant_context(
        state,
        chunks,
        web_results,
    )
    trace.append(relevance_trace)

    references = _references_from_chunks(chunks)
    return {
        "retrieved_chunks": chunks,
        "references": references
        + _web_references_from_results(web_results, offset=len(references)),
        "web_results": web_results,
        "retrieval_attempts": min(
            state.max_retrieval_attempts,
            state.retrieval_attempts + (2 if should_expand else 1),
        ),
        "errors": errors,
        "trace": trace,
    }


def prepare_action_node(state: AgentState) -> dict:
    action_type = WRITE_INTENTS.get(state.intent, "none")
    if action_type == "none":
        return {"approval_status": "not_required"}

    context_blocks = []
    for index, chunk in enumerate(state.retrieved_chunks[:5], start=1):
        context_blocks.append(
            f"[{index}] {chunk.title or chunk.file_name or chunk.source_type}\n"
            f"Source type: {chunk.source_type}\n"
            f"Text:\n{chunk.text[:1500]}"
        )
    prompt = {
        "requested_action_type": action_type,
        "user_query": state.query,
        "plan": state.plan,
        "profile": state.agent_profile,
        "runtime_context": state.runtime_context,
        "recent_conversation": _recent_history(state.conversation_history),
        "retrieved_context": "\n\n---\n\n".join(context_blocks),
    }

    try:
        raw = invoke_with_fallback(
            [
                SystemMessage(content=ACTION_PROPOSAL_PROMPT),
                HumanMessage(content=json.dumps(prompt)),
            ]
        )
        proposal = _parse_json_model(raw, ActionProposal)
        if proposal.action_type != action_type:
            proposal.action_type = action_type
        action_payload = {
            "action_type": proposal.action_type,
            "description": proposal.description,
            "payload": proposal.payload,
            "requires_approval": True,
            "risk_level": proposal.risk_level,
            "confirmation_summary": proposal.confirmation_summary,
        }
        action_payload = _resolve_action_payload(state, action_payload)
        guardrail_warning = None
        try:
            validate_action(action_payload)
        except ActionGuardrailError as exc:
            guardrail_warning = str(exc)
    except Exception as exc:
        action_payload = {
            "action_type": action_type,
            "description": (
                "I could not safely infer every required field for this "
                "write action. Please provide the missing details and ask again."
            ),
            "payload": {"query": state.query},
            "requires_approval": True,
            "risk_level": "medium",
            "confirmation_summary": f"Proposal generation failed: {exc}",
        }
        guardrail_warning = str(exc)

    action = ProposedAction(
        action_type=action_payload["action_type"],
        description=action_payload["description"],
        payload=action_payload["payload"],
        requires_approval=True,
        risk_level=action_payload["risk_level"],
        confirmation_summary=action_payload["confirmation_summary"],
        guardrail_warning=guardrail_warning,
    )
    return {
        "proposed_action": action,
        "approval_status": "pending",
        "trace": state.trace + [f"prepared action={action_type}"],
    }


def answer_node(state: AgentState) -> dict:
    if state.proposed_action:
        warning = state.proposed_action.guardrail_warning
        summary = state.proposed_action.confirmation_summary
        draft = (
            "## Approval required\n\n"
            f"{state.proposed_action.description}\n\n"
            f"**Action:** `{state.proposed_action.action_type}`\n\n"
            f"**Risk:** {state.proposed_action.risk_level}\n\n"
            f"**Preview:** {summary or 'Review the action details below.'}\n\n"
            "I have not executed this action yet. Use the approval button only "
            "after checking the preview."
        )
        if warning:
            draft += f"\n\n**Needs attention:** {warning}"
        return {"draft_answer": draft}

    context_blocks = []
    for index, chunk in enumerate(state.retrieved_chunks, start=1):
        context_blocks.append(
            f"[{index}] {chunk.title or chunk.file_name or chunk.source_type}\n"
            f"Source type: {chunk.source_type}\n"
            f"Text:\n{chunk.text}"
        )

    if not context_blocks and not state.web_results:
        if state.intent == "table_analysis":
            table_sources = [
                document for document in MetadataStore().list_documents(state.user_id, limit=50)
                if document.get("index_status") == "table_source"
            ]
            if table_sources:
                names = "\n".join(
                    f"- {document.get('file_name')} ({document.get('source')})"
                    for document in table_sources[:8]
                )
                draft = (
                    "## Table source available\n\n"
                    "I found table files registered for analytics, and they were "
                    "intentionally not vector-indexed. Row-level questions should "
                    "run through the table analytics path instead of RAG chunks.\n\n"
                    f"**Available table sources:**\n{names}\n\n"
                    "The current analytics adapter is conservative; ask for row "
                    "count, columns, filters, or summaries and I will route it to "
                    "the table engine when the local table file is available."
                )
                return {
                    "draft_answer": draft,
                    "trace": state.trace + ["table source not vectorized"],
                }

        if state.errors:
            draft = (
                "## I could not retrieve your indexed documents\n\n"
                "The workspace search step failed before I could read the "
                "document chunks.\n\n"
                "**What happened:**\n"
                f"- {state.errors[-1]}\n\n"
                "**What to check:**\n"
                "- Make sure Qdrant is running.\n"
                "- Make sure the file upload/sync job finished as `indexed`.\n"
                "- Try the search endpoint with the same question to confirm "
                "chunks are searchable."
            )
        else:
            draft = (
                "## I could not find matching indexed context\n\n"
                "I searched the workspace index, but did not find a relevant "
                "chunk for this question.\n\n"
                "**Next steps:**\n"
                "- Confirm the document appears in **Indexed documents** with "
                "status `indexed`.\n"
                "- If it was just uploaded, wait for indexing to finish and ask again.\n"
                "- Try a more specific phrase from the document."
            )
        return {
            "draft_answer": draft,
            "trace": state.trace + ["no retrieved context"],
        }

    context = "\n\n---\n\n".join(context_blocks) or "No retrieved context."
    history = _recent_history(state.conversation_history)
    prompt = f"""
{_profile_context(state)}

{_runtime_context(state)}

Recent conversation:
{history or "No previous turns."}

User query:
{state.query}

Execution plan:
{json.dumps(state.plan)}

Retrieved context:
{context}

Web search context:
{_web_context(state)}
""".strip()

    try:
        draft = invoke_with_fallback(
            [
                SystemMessage(content=ANSWER_PROMPT),
                HumanMessage(content=prompt),
            ]
        )
    except Exception as exc:
        snippets = []
        for index, chunk in enumerate(state.retrieved_chunks[:3], start=1):
            text = chunk.text.strip().replace("\n", " ")
            snippets.append(f"[{index}] {text[:450]}")
        draft = (
            "I found relevant workspace context, but the generation model is "
            f"not available right now: {exc}\n\n"
            "Top retrieved context:\n"
            + "\n\n".join(snippets)
        )
    return {
        "draft_answer": draft,
        "trace": state.trace + ["draft answer generated"],
    }


def formatter_node(state: AgentState) -> dict:
    if not state.draft_answer:
        return {"final_answer": ""}

    try:
        formatted = invoke_with_fallback(
            [
                SystemMessage(content=FORMATTER_PROMPT),
                HumanMessage(content=state.draft_answer),
            ]
        )
    except Exception:
        formatted = state.draft_answer
    return {
        "final_answer": formatted,
        "trace": state.trace + ["formatter applied"],
    }
