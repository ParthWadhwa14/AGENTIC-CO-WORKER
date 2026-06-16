from typing import Literal

from pydantic import BaseModel, Field


class RouteDecision(BaseModel):
    intent: Literal[
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
    sources_needed: list[str] = Field(default_factory=list)
    needs_retrieval: bool = True
    needs_table_engine: bool = False
    needs_write_action: bool = False
    confidence: float = 0.0
    reasoning: str = ""


class ActionPlan(BaseModel):
    steps: list[str]
    needs_approval: bool = False
    action_type: str = "none"


class ActionProposal(BaseModel):
    action_type: str
    description: str
    payload: dict = Field(default_factory=dict)
    risk_level: Literal["low", "medium", "high"] = "medium"
    confirmation_summary: str = ""
