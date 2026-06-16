from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.agent.service import run_agent, stream_agent
from app.services.action_executor import ActionGuardrailError, execute_action


router = APIRouter(prefix="/agent", tags=["agent"])


class AgentRequest(BaseModel):
    user_id: str = "local-user"
    query: str
    history: list[dict[str, str]] = Field(default_factory=list)
    mode: str = Field(default="workspace", pattern="^(workspace|basic)$")
    use_web_search: bool = True
    pinned_document_ids: list[str] = Field(default_factory=list)
    source_type: str | None = None
    limit: int = Field(default=8, ge=1, le=20)


class AgentProfileRequest(BaseModel):
    user_id: str
    agent_description: str = ""
    user_context: str = ""
    response_preferences: str = ""


class ExecuteActionRequest(BaseModel):
    user_id: str
    action: dict
    approved: bool = False


@router.post("/ask")
def ask_agent(request: AgentRequest):
    try:
        return run_agent(
            user_id=request.user_id,
            query=request.query,
            conversation_history=request.history,
            source_type=request.source_type,
            limit=request.limit,
            mode=request.mode,
            use_web_search=request.use_web_search,
            pinned_document_ids=request.pinned_document_ids,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/stream")
def stream_agent_answer(request: AgentRequest):
    try:
        return StreamingResponse(
            stream_agent(
                user_id=request.user_id,
                query=request.query,
                conversation_history=request.history,
                source_type=request.source_type,
                limit=request.limit,
            ),
            media_type="text/event-stream",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/profile")
def get_agent_profile(user_id: str):
    from app.storage.metadata_store import MetadataStore

    return MetadataStore().get_agent_profile(user_id)


@router.put("/profile")
def update_agent_profile(request: AgentProfileRequest):
    from app.storage.metadata_store import MetadataStore

    return MetadataStore().upsert_agent_profile(
        user_id=request.user_id,
        agent_description=request.agent_description,
        user_context=request.user_context,
        response_preferences=request.response_preferences,
    )


@router.post("/actions/execute")
def execute_agent_action(request: ExecuteActionRequest):
    if not request.approved:
        raise HTTPException(
            status_code=403,
            detail="Action execution requires explicit user approval.",
        )

    try:
        return execute_action(user_id=request.user_id, action=request.action)
    except ActionGuardrailError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
