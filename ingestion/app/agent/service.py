import json
from collections.abc import Iterable

from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.graph import agent_graph
from app.agent.llm import stream_with_fallback
from app.agent.llm import invoke_with_fallback
from app.agent.prompts import BASIC_CHAT_PROMPT, FORMATTER_PROMPT
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


def run_basic_chat(
    user_id: str,
    query: str,
    conversation_history: list[dict[str, str]] | None = None,
    use_web_search: bool = True,
) -> dict:
    metadata_store = MetadataStore()
    profile = metadata_store.get_agent_profile(user_id)
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
) -> dict:
    if mode == "basic":
        return run_basic_chat(
            user_id=user_id,
            query=query,
            conversation_history=conversation_history,
            use_web_search=use_web_search,
        )

    profile = MetadataStore().get_agent_profile(user_id)
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
