import json
from collections.abc import Iterable

from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.graph import agent_graph
from app.agent.llm import stream_with_fallback
from app.agent.llm import invoke_with_fallback
from app.agent.prompts import BASIC_CHAT_PROMPT, FORMATTER_PROMPT, MEMORY_EXTRACTION_PROMPT
from app.agent.state import AgentState
from app.services.runtime_context import runtime_context, runtime_context_text
from app.services.web_search import serper_search, should_search_web
from app.storage.metadata_store import MetadataStore


def _state_to_response(state: AgentState) -> dict:
    return {
        "answer": state.final_answer,
        "references": state.references,
        "intent": state.intent,
        "plan": state.plan,
        "approval_status": state.approval_status,
        "proposed_action": (
            state.proposed_action.model_dump()
            if state.proposed_action else None
        ),
        "trace": state.trace,
        "errors": state.errors,
    }


def _history_text(history: list[dict[str, str]], max_turns: int = 8) -> str:
    lines = []
    for message in history[-max_turns:]:
        role = message.get("role", "user")
        content = (message.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _profile_text(profile: dict) -> str:
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


def _parse_json_object(raw: str) -> dict:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.removeprefix("json").strip()
    return json.loads(cleaned)


TRANSIENT_MEMORY_LABELS = {
    "task",
    "current task",
    "goal",
    "current goal",
    "requested action",
    "email",
    "recipient",
    "attachment",
    "draft",
}


def _sanitize_user_context(user_context: str) -> str:
    kept = []
    for raw_line in user_context.splitlines():
        line = raw_line.strip()
        normalized = line.lstrip("-* ").strip()
        label = normalized.split(":", 1)[0].strip().lower().strip("*")
        if label in TRANSIENT_MEMORY_LABELS:
            continue
        if any(
            phrase in normalized.lower()
            for phrase in [
                "draft email",
                "send email",
                "attached document",
                "attached documents",
                "earnmoneynow",
            ]
        ):
            continue
        kept.append(raw_line)
    return "\n".join(kept).strip()


def _user_messages_for_memory(
    query: str,
    conversation_history: list[dict[str, str]] | None = None,
) -> list[str]:
    messages = [
        (message.get("content") or "").strip()
        for message in conversation_history or []
        if message.get("role") == "user" and (message.get("content") or "").strip()
    ]
    if query.strip():
        messages.append(query.strip())
    return messages


def _profile_with_chat_memory(
    metadata_store: MetadataStore,
    user_id: str,
    profile: dict,
    query: str,
    conversation_history: list[dict[str, str]] | None = None,
) -> dict:
    existing_user_context = profile.get("user_context") or ""
    sanitized_existing_user_context = _sanitize_user_context(existing_user_context)
    user_messages = _user_messages_for_memory(query, conversation_history)
    if not user_messages:
        if sanitized_existing_user_context != existing_user_context.strip():
            return metadata_store.upsert_agent_profile(
                user_id=user_id,
                agent_description=profile.get("agent_description") or "",
                user_context=sanitized_existing_user_context,
                response_preferences=profile.get("response_preferences") or "",
            )
        return profile

    memory_input = {
        "existing_user_context": sanitized_existing_user_context,
        "user_messages": user_messages,
    }
    try:
        raw = invoke_with_fallback(
            [
                SystemMessage(content=MEMORY_EXTRACTION_PROMPT),
                HumanMessage(content=json.dumps(memory_input)),
            ]
        )
        parsed = _parse_json_object(raw)
        user_context = _sanitize_user_context(parsed.get("user_context") or "")
    except Exception:
        return profile

    if not user_context or user_context == sanitized_existing_user_context:
        return profile

    return metadata_store.upsert_agent_profile(
        user_id=user_id,
        agent_description=profile.get("agent_description") or "",
        user_context=user_context,
        response_preferences=profile.get("response_preferences") or "",
    )


def run_basic_chat(
    user_id: str,
    query: str,
    conversation_history: list[dict[str, str]] | None = None,
    use_web_search: bool = True,
) -> dict:
    metadata_store = MetadataStore()
    profile = metadata_store.get_agent_profile(user_id)
    profile = _profile_with_chat_memory(
        metadata_store,
        user_id,
        profile,
        query,
        conversation_history,
    )
    history = _history_text(conversation_history or [])
    web_results = []
    if use_web_search and should_search_web(query):
        web_results = serper_search(query)

    web_context = "\n".join(
        f"[{index}] {result.get('title')}\n"
        f"URL: {result.get('link')}\n"
        f"Snippet: {result.get('snippet')}"
        for index, result in enumerate(web_results, start=1)
    )
    prompt = f"""
{runtime_context_text()}

{_profile_text(profile)}

Recent conversation:
{history or "No previous turns."}

Web search context:
{web_context or "No web search context used."}

User query:
{query}
""".strip()

    draft = invoke_with_fallback(
        [
            SystemMessage(content=BASIC_CHAT_PROMPT),
            HumanMessage(content=prompt),
        ]
    )
    try:
        answer = invoke_with_fallback(
            [
                SystemMessage(content=FORMATTER_PROMPT),
                HumanMessage(content=draft),
            ]
        )
    except Exception:
        answer = draft

    return {
        "answer": answer,
        "references": [
            {
                "ref": index,
                "title": result.get("title") or result.get("link") or "Web result",
                "file_name": result.get("title") or result.get("link") or "Web result",
                "open_url": result.get("link"),
                "source_type": "web",
                "metadata": {"snippet": result.get("snippet"), "date": result.get("date")},
            }
            for index, result in enumerate(web_results, start=1)
            if result.get("link")
        ],
        "intent": "basic_chat",
        "plan": ["Answer as a professional agentic co-worker."],
        "approval_status": "not_required",
        "proposed_action": None,
        "trace": ["basic chat", f"web_results={len(web_results)}"],
        "errors": [],
    }


def run_agent(
    user_id: str,
    query: str,
    conversation_history: list[dict[str, str]] | None = None,
    source_type: str | None = None,
    limit: int = 8,
    mode: str = "workspace",
    use_web_search: bool = True,
    pinned_document_ids: list[str] | None = None,
    priority_document_ids: list[str] | None = None,
) -> dict:
    if mode == "basic":
        return run_basic_chat(
            user_id=user_id,
            query=query,
            conversation_history=conversation_history,
            use_web_search=use_web_search,
        )

    metadata_store = MetadataStore()
    profile = metadata_store.get_agent_profile(user_id)
    profile = _profile_with_chat_memory(
        metadata_store,
        user_id,
        profile,
        query,
        conversation_history,
    )
    current_context = runtime_context()
    web_results = []
    if use_web_search and should_search_web(query):
        try:
            web_results = serper_search(query)
        except Exception:
            web_results = []
    initial_state = AgentState(
        user_id=user_id,
        query=query,
        conversation_history=conversation_history or [],
        agent_profile=profile,
        runtime_context=current_context,
        web_results=web_results,
        pinned_document_ids=pinned_document_ids or [],
        priority_document_ids=priority_document_ids or [],
        allow_web_search=use_web_search,
        requested_source_type=source_type,
        limit=limit,
    )
    result = agent_graph.invoke(initial_state)
    state = AgentState.model_validate(result)
    return _state_to_response(state)


def stream_agent(
    user_id: str,
    query: str,
    conversation_history: list[dict[str, str]] | None = None,
    source_type: str | None = None,
    limit: int = 8,
) -> Iterable[str]:
    initial_state = AgentState(
        user_id=user_id,
        query=query,
        conversation_history=conversation_history or [],
        requested_source_type=source_type,
        limit=limit,
    )
    result = agent_graph.invoke(initial_state)
    state = AgentState.model_validate(result)

    metadata = {
        "type": "metadata",
        "intent": state.intent,
        "plan": state.plan,
        "references": state.references,
        "approval_status": state.approval_status,
        "proposed_action": (
            state.proposed_action.model_dump()
            if state.proposed_action else None
        ),
    }
    yield f"data: {json.dumps(metadata)}\n\n"

    text_to_stream = state.draft_answer or state.final_answer or ""
    stream_prompt = (
        "Format and stream this answer for the UI. Do not add inline citation "
        "markers or a reference section; the UI renders source links below.\n\n"
        f"{text_to_stream}"
    )
    for token in stream_with_fallback(
        [
            SystemMessage(content=FORMATTER_PROMPT),
            HumanMessage(content=stream_prompt),
        ]
    ):
        yield f"data: {json.dumps({'type': 'token', 'text': token})}\n\n"

    yield f"data: {json.dumps({'type': 'done'})}\n\n"
