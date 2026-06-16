import json

from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.llm import invoke_with_fallback
from app.agent.prompts import (
    ACTION_PROPOSAL_PROMPT,
    ANSWER_PROMPT,
    FORMATTER_PROMPT,
    PLANNER_PROMPT,
    ROUTER_PROMPT,
)
from app.agent.schemas import ActionPlan, ActionProposal, RouteDecision
from app.agent.state import AgentState, ProposedAction, RetrievedChunk
from app.services.action_executor import ActionGuardrailError, validate_action
from app.services.rate_limiter import RateLimitError, check_rate_limit
from app.storage.metadata_store import MetadataStore
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
        for index, result in enumerate(state.web_results, start=1)
        if result.get("link")
    ]


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
    elif any(
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
    if decision.intent == "general_chat":
        needs_retrieval = _should_retrieve_general_query(state.query)
    if decision.intent in WRITE_INTENTS and not decision.sources_needed:
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

    live_pinned_chunks: list[RetrievedChunk] = []
    live_pinned_refs: list[dict] = []
    if any(
        document_id.startswith(LIVE_GMAIL_PREFIX)
        for document_id in state.pinned_document_ids
    ):
        live_pinned_chunks, live_pinned_refs = _live_gmail_retrieve(state)

    source_types = state.sources_needed or DEFAULT_SOURCE_TYPES
    if state.intent == "gmail_search":
        live_chunks, live_refs = (
            (live_pinned_chunks, live_pinned_refs)
            if live_pinned_chunks else _live_gmail_retrieve(state)
        )
        if live_chunks:
            return {
                "retrieved_chunks": live_chunks,
                "references": live_refs + _web_references(
                    state,
                    offset=len(live_refs),
                ),
                "trace": state.trace + [
                    f"live gmail retrieved {len(live_chunks)} messages"
                ],
            }
        source_types = ["gmail"]
    elif state.intent == "table_analysis":
        source_types = ["csv", "xlsx", "google_sheet"]
    elif state.requested_source_type:
        source_types = [state.requested_source_type]

    non_live_document_ids = [
        document_id for document_id in state.pinned_document_ids
        if not document_id.startswith(LIVE_GMAIL_PREFIX)
    ]
    if state.pinned_document_ids and live_pinned_chunks and not non_live_document_ids:
        return {
            "retrieved_chunks": live_pinned_chunks,
            "references": live_pinned_refs + _web_references(
                state,
                offset=len(live_pinned_refs),
            ),
            "trace": state.trace + [
                f"retrieved {len(live_pinned_chunks)} pinned live gmail messages"
            ],
        }

    try:
        search_query = _history_aware_query(state)
        chunks, references = RetrievalTools().search_workspace(
            query=search_query,
            source_types=source_types,
            limit=state.limit,
            document_ids=non_live_document_ids or None,
        )
    except Exception as exc:
        return {
            "retrieved_chunks": [],
            "references": _web_references(state),
            "errors": state.errors + [str(exc)],
            "trace": state.trace + [f"retrieval failed: {exc}"],
        }

    return {
        "retrieved_chunks": live_pinned_chunks + chunks,
        "references": (
            live_pinned_refs
            + references
            + _web_references(
                state,
                offset=len(live_pinned_refs) + len(references),
            )
        ),
        "trace": state.trace + [f"retrieved {len(chunks)} chunks"],
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
