from typing import Any, Literal

from pydantic import BaseModel, Field


IntentType = Literal[
    "document_search",
    "document_qa",
    "gmail_search",
    "gmail_draft",
    "gmail_send",
    "table_analysis",
    "docs_create",
    "docs_update",
    "sheets_create",
    "sheets_update",
    "general_chat",
    "unknown",
]


class RetrievedChunk(BaseModel):
    chunk_id: str | None = None
    document_id: str | None = None
    source_type: str
    file_name: str | None = None
    title: str | None = None
    text: str
    score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    reference: dict[str, Any] | None = None


class ProposedAction(BaseModel):
    action_type: str
    description: str
    payload: dict[str, Any] = Field(default_factory=dict)
    requires_approval: bool = True
    risk_level: Literal["low", "medium", "high"] = "medium"
    confirmation_summary: str = ""
    guardrail_warning: str | None = None


class AgentState(BaseModel):
    user_id: str
    query: str
    conversation_history: list[dict[str, str]] = Field(default_factory=list)
    agent_profile: dict[str, Any] = Field(default_factory=dict)
    runtime_context: dict[str, Any] = Field(default_factory=dict)
    web_results: list[dict[str, Any]] = Field(default_factory=list)
    pinned_document_ids: list[str] = Field(default_factory=list)
    priority_document_ids: list[str] = Field(default_factory=list)
    allow_web_search: bool = True
    limit: int = 8
    requested_source_type: str | None = None
    max_retrieval_attempts: int = 2
    retrieval_attempts: int = 0

    intent: IntentType = "unknown"
    sources_needed: list[str] = Field(default_factory=list)
    needs_retrieval: bool = True
    needs_write_action: bool = False
    plan: list[str] = Field(default_factory=list)

    retrieved_chunks: list[RetrievedChunk] = Field(default_factory=list)
    table_results: dict[str, Any] | None = None
    proposed_action: ProposedAction | None = None
    approval_status: Literal[
        "not_required",
        "pending",
        "approved",
        "rejected",
    ] = "not_required"

    draft_answer: str | None = None
    final_answer: str | None = None
    references: list[dict[str, Any]] = Field(default_factory=list)

    errors: list[str] = Field(default_factory=list)
    trace: list[str] = Field(default_factory=list)
