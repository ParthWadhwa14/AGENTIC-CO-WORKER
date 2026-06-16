import json

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.agent.llm import invoke_with_fallback
from app.agent.prompts import SOURCE_DISCOVERY_PROMPT
from app.connectors.google_drive import (
    GOOGLE_DOC_MIME_TYPE,
    GOOGLE_SHEET_MIME_TYPE,
)
from app.services.ingestion_jobs import process_ingestion_job
from app.services.rate_limiter import RateLimitError, check_rate_limit
from app.storage.metadata_store import MetadataStore, utc_now
from app.sync.drive_sync import DriveSyncService
from app.sync.gmail_sync import DEFAULT_GMAIL_QUERY, GmailSyncService


router = APIRouter(tags=["sources-scopes"])


class ScopeResourceRequest(BaseModel):
    provider: str
    resource_type: str
    name: str
    external_id: str | None = None
    parent_external_id: str | None = None
    mime_type: str | None = None
    web_url: str | None = None
    selector: dict = Field(default_factory=dict)


class AgentIngestRequest(BaseModel):
    user_id: str
    focus: str = ""
    providers: list[str] = Field(default_factory=list)
    auto_ingest: bool = False


class PlannedSearch(BaseModel):
    provider: str
    query: str
    max_results: int = Field(default=5, ge=3, le=10)


class SourceDiscoveryPlan(BaseModel):
    searches: list[PlannedSearch] = Field(default_factory=list)


def _parse_json_model(raw: str, model):
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.removeprefix("json").strip()
    return model.model_validate_json(cleaned)


def _fallback_discovery_plan(focus: str = "") -> SourceDiscoveryPlan:
    target = focus.strip()
    if target:
        return SourceDiscoveryPlan(
            searches=[
                PlannedSearch(provider="drive", query=target, max_results=5),
                PlannedSearch(provider="docs", query=target, max_results=5),
                PlannedSearch(provider="sheets", query=target, max_results=5),
                PlannedSearch(
                    provider="gmail",
                    query=f"{target} newer_than:365d -in:spam -in:trash",
                    max_results=5,
                ),
            ]
        )

    return SourceDiscoveryPlan(
        searches=[
            PlannedSearch(provider="drive", query="resume project", max_results=5),
            PlannedSearch(provider="docs", query="notes plan draft", max_results=5),
            PlannedSearch(provider="sheets", query="tracker", max_results=5),
            PlannedSearch(
                provider="gmail",
                query="newer_than:180d (important OR project OR interview OR recruiter) -in:spam -in:trash",
                max_results=5,
            ),
        ]
    )


def _safe_gmail_query(query: str) -> str:
    query = query.strip() or DEFAULT_GMAIL_QUERY
    if "-in:spam" not in query:
        query += " -in:spam"
    if "-in:trash" not in query:
        query += " -in:trash"
    if "newer_than:" not in query and "after:" not in query:
        query += " newer_than:365d"
    return query


def _provider_mime_type(provider: str) -> str | None:
    if provider == "docs":
        return GOOGLE_DOC_MIME_TYPE
    if provider == "sheets":
        return GOOGLE_SHEET_MIME_TYPE
    return None


def _gmail_preview(message: dict, gmail: GmailSyncService) -> dict:
    headers = gmail.gmail.extract_headers(message)
    return {
        "id": message.get("id"),
        "thread_id": message.get("threadId"),
        "snippet": message.get("snippet"),
        "label_ids": message.get("labelIds", []),
        "subject": headers.get("subject") or "(no subject)",
        "from": headers.get("from"),
        "to": headers.get("to"),
        "date": headers.get("date"),
    }


def _queue_drive_resource(
    drive: DriveSyncService,
    resource: dict,
) -> list[dict]:
    selector = resource.get("selector") or {}
    resource_type = resource["resource_type"]
    queued = []

    if resource_type == "folder":
        queued.extend(
            _queue_folder(
                drive,
                folder_id=resource["external_id"],
                recursive=bool(selector.get("recursive", False)),
                allowed_mime_types=selector.get("allowed_mime_types") or [],
            )
        )
        return queued

    file = {
        "id": resource["external_id"],
        "name": resource["name"],
        "mimeType": resource.get("mime_type"),
        "webViewLink": resource.get("web_url"),
        "md5Checksum": None,
        "modifiedTime": None,
    }
    job = drive.queue_file_for_ingestion(file, reason="selected_scope_ingest")
    if job:
        queued.append(job)
    return queued


def _queue_folder(
    drive: DriveSyncService,
    folder_id: str,
    recursive: bool = False,
    allowed_mime_types: list[str] | None = None,
) -> list[dict]:
    queued = []
    page_token = None
    allowed = set(allowed_mime_types or [])

    while True:
        result = drive.drive.list_folder_children(
            folder_id=folder_id,
            page_token=page_token,
        )
        for file in result.get("files", []):
            mime_type = file.get("mimeType")
            if mime_type == "application/vnd.google-apps.folder":
                if recursive:
                    queued.extend(
                        _queue_folder(
                            drive,
                            folder_id=file["id"],
                            recursive=True,
                            allowed_mime_types=allowed_mime_types,
                        )
                    )
                continue

            if allowed and mime_type not in allowed:
                continue
            if not drive.is_supported(file):
                continue

            job = drive.queue_file_for_ingestion(
                file,
                reason="selected_scope_folder_ingest",
            )
            if job:
                queued.append(job)

        page_token = result.get("nextPageToken")
        if not page_token:
            break

    return queued


def _ingest_scope_resources(user_id: str) -> dict:
    metadata_store = MetadataStore()
    scope = metadata_store.get_or_create_default_scope(user_id)
    resources = metadata_store.list_scope_resources(user_id, scope["id"])
    queued_jobs = []
    gmail_results = []

    drive_service = None
    gmail_service = None

    for resource in resources:
        if not resource.get("ingest_enabled"):
            continue

        provider = resource["provider"]
        selector = resource.get("selector") or {}
        try:
            if provider in {"google_drive", "google_docs", "google_sheets"}:
                drive_service = drive_service or DriveSyncService(
                    user_id=user_id,
                    metadata_store=metadata_store,
                )
                jobs = _queue_drive_resource(drive_service, resource)
                queued_jobs.extend(jobs)
                for job in jobs:
                    if not job.get("job_id") or not job.get("local_path"):
                        continue
                    process_ingestion_job(
                        job["job_id"],
                        job["document_id"],
                        job["local_path"],
                        metadata_store=metadata_store,
                    )
                metadata_store.update_scope_resource_status(
                    resource["id"],
                    "indexed",
                    last_synced_at=utc_now(),
                    last_ingested_at=utc_now(),
                )

            elif provider == "gmail":
                gmail_service = gmail_service or GmailSyncService(
                    user_id=user_id,
                    metadata_store=metadata_store,
                )
                if resource["resource_type"] == "gmail_thread":
                    thread = gmail_service.gmail.get_thread(resource["external_id"])
                    indexed = []
                    for message in thread.get("messages", []):
                        indexed.append(gmail_service.index_message(message["id"]))
                    result = {
                        "resource": resource["name"],
                        "indexed_messages": indexed,
                    }
                else:
                    result = gmail_service.initial_sync(
                        query=selector.get("q") or DEFAULT_GMAIL_QUERY,
                        label_ids=selector.get("labelIds") or None,
                        max_messages=int(selector.get("max_messages", 100)),
                    )
                gmail_results.append(result)
                metadata_store.update_scope_resource_status(
                    resource["id"],
                    "indexed",
                    last_synced_at=utc_now(),
                    last_ingested_at=utc_now(),
                )
        except Exception:
            metadata_store.update_scope_resource_status(resource["id"], "failed")
            raise

    return {
        "scope": scope,
        "resources_considered": len(resources),
        "queued_drive_jobs": queued_jobs,
        "gmail_results": gmail_results,
    }


def _plan_agent_discovery(
    metadata_store: MetadataStore,
    user_id: str,
    focus: str,
    providers: list[str],
) -> SourceDiscoveryPlan:
    profile = metadata_store.get_agent_profile(user_id)
    requested_providers = providers or ["drive", "docs", "sheets", "gmail"]
    try:
        raw = invoke_with_fallback(
            [
                SystemMessage(content=SOURCE_DISCOVERY_PROMPT),
                HumanMessage(
                    content=json.dumps(
                        {
                            "focus": focus,
                            "providers": requested_providers,
                            "agent_profile": profile,
                        }
                    )
                ),
            ]
        )
        plan = _parse_json_model(raw, SourceDiscoveryPlan)
    except Exception:
        plan = _fallback_discovery_plan(focus)

    allowed = set(requested_providers)
    searches = [
        search for search in plan.searches
        if search.provider in {"drive", "docs", "sheets", "gmail"}
        and search.provider in allowed
    ][:6]
    if not searches:
        searches = _fallback_discovery_plan(focus).searches[:4]
    return SourceDiscoveryPlan(searches=searches)


def _add_drive_discovery_results(
    metadata_store: MetadataStore,
    scope: dict,
    user_id: str,
    provider: str,
    query: str,
    max_results: int,
) -> list[dict]:
    service = DriveSyncService(user_id=user_id, metadata_store=metadata_store)
    result = service.drive.discover_files(
        query=query,
        mime_type=_provider_mime_type(provider),
        page_size=max_results,
    )
    added = []
    for file in result.get("files", [])[:max_results]:
        resource = metadata_store.add_scope_resource(
            user_id=user_id,
            scope_id=scope["id"],
            provider=(
                "google_docs" if provider == "docs"
                else "google_sheets" if provider == "sheets"
                else "google_drive"
            ),
            resource_type=(
                "google_doc" if provider == "docs"
                else "spreadsheet" if provider == "sheets"
                else "folder" if file.get("mimeType") == "application/vnd.google-apps.folder"
                else "file"
            ),
            name=file.get("name") or file["id"],
            external_id=file.get("id"),
            parent_external_id=(file.get("parents") or [None])[0],
            mime_type=file.get("mimeType"),
            web_url=file.get("webViewLink"),
            selector={
                "mode": "whole_resource",
                "query_used": query,
                "agent_selected": True,
            },
        )
        added.append(resource)
    return added


def _add_gmail_discovery_query(
    metadata_store: MetadataStore,
    scope: dict,
    user_id: str,
    query: str,
    max_results: int,
) -> dict:
    safe_query = _safe_gmail_query(query)
    return metadata_store.add_scope_resource(
        user_id=user_id,
        scope_id=scope["id"],
        provider="gmail",
        resource_type="gmail_query",
        name=f"Agent Gmail search: {safe_query}",
        selector={
            "q": safe_query,
            "max_messages": min(max_results * 10, 100),
            "agent_selected": True,
        },
    )


@router.get("/sources/drive/search")
def search_drive_sources(
    user_id: str = Query(...),
    q: str = Query(""),
    mime_type: str | None = Query(None),
    page_size: int = Query(25, ge=1, le=50),
):
    try:
        service = DriveSyncService(user_id=user_id)
        result = service.drive.discover_files(
            query=q,
            mime_type=mime_type,
            page_size=page_size,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return result


@router.get("/sources/docs/search")
def search_docs_sources(
    user_id: str = Query(...),
    q: str = Query(""),
    page_size: int = Query(25, ge=1, le=50),
):
    return search_drive_sources(
        user_id=user_id,
        q=q,
        mime_type=GOOGLE_DOC_MIME_TYPE,
        page_size=page_size,
    )


@router.get("/sources/sheets/search")
def search_sheets_sources(
    user_id: str = Query(...),
    q: str = Query(""),
    page_size: int = Query(25, ge=1, le=50),
):
    return search_drive_sources(
        user_id=user_id,
        q=q,
        mime_type=GOOGLE_SHEET_MIME_TYPE,
        page_size=page_size,
    )


@router.get("/sources/drive/folders")
def list_drive_folders(
    user_id: str = Query(...),
    page_size: int = Query(50, ge=1, le=100),
):
    try:
        service = DriveSyncService(user_id=user_id)
        return service.drive.list_folders(page_size=page_size)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/sources/drive/folder/{folder_id}/children")
def list_drive_folder_children(
    folder_id: str,
    user_id: str = Query(...),
    page_size: int = Query(50, ge=1, le=100),
):
    try:
        service = DriveSyncService(user_id=user_id)
        return service.drive.list_folder_children(
            folder_id=folder_id,
            page_size=page_size,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/sources/gmail/labels")
def list_gmail_source_labels(user_id: str = Query(...)):
    try:
        service = GmailSyncService(user_id=user_id)
        return {"labels": service.gmail.list_labels()}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/sources/gmail/search")
def search_gmail_sources(
    user_id: str = Query(...),
    q: str = Query(DEFAULT_GMAIL_QUERY),
    max_results: int = Query(10, ge=1, le=25),
):
    try:
        service = GmailSyncService(user_id=user_id)
        messages = service.gmail.search_message_metadata(
            query=q,
            max_results=max_results,
        )
        return {
            "query": q,
            "messages": [_gmail_preview(message, service) for message in messages],
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/scopes/default")
def get_default_scope(user_id: str = Query(...)):
    metadata_store = MetadataStore()
    scope = metadata_store.get_or_create_default_scope(user_id)
    return {
        "scope": scope,
        "resources": metadata_store.list_scope_resources(user_id, scope["id"]),
    }


@router.post("/scopes/default/resources")
def add_default_scope_resource(
    resource: ScopeResourceRequest,
    user_id: str = Query(...),
):
    metadata_store = MetadataStore()
    scope = metadata_store.get_or_create_default_scope(user_id)
    added = metadata_store.add_scope_resource(
        user_id=user_id,
        scope_id=scope["id"],
        provider=resource.provider,
        resource_type=resource.resource_type,
        name=resource.name,
        external_id=resource.external_id,
        parent_external_id=resource.parent_external_id,
        mime_type=resource.mime_type,
        web_url=resource.web_url,
        selector=resource.selector,
    )
    return {"scope": scope, "resource": added}


@router.delete("/scopes/resources/{resource_id}")
def delete_scope_resource(resource_id: str, user_id: str = Query(...)):
    MetadataStore().remove_scope_resource(user_id, resource_id)
    return {"status": "deleted", "resource_id": resource_id}


@router.post("/scopes/default/ingest")
def ingest_default_scope(
    background_tasks: BackgroundTasks,
    user_id: str = Query(...),
    background: bool = Query(True),
):
    if background:
        background_tasks.add_task(_ingest_scope_resources, user_id)
        return {"status": "queued"}

    return {"status": "completed", "result": _ingest_scope_resources(user_id)}


@router.post("/scopes/default/agent-ingest")
def agent_ingest_default_scope(
    request: AgentIngestRequest,
    background_tasks: BackgroundTasks,
):
    try:
        check_rate_limit(
            f"agent_ingest:{request.user_id}",
            max_calls=4,
            window_seconds=300,
        )
    except RateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc

    metadata_store = MetadataStore()
    scope = metadata_store.get_or_create_default_scope(request.user_id)
    plan = _plan_agent_discovery(
        metadata_store=metadata_store,
        user_id=request.user_id,
        focus=request.focus,
        providers=request.providers,
    )

    added_resources = []
    search_summaries = []
    for search in plan.searches:
        if search.provider == "gmail":
            resource = _add_gmail_discovery_query(
                metadata_store=metadata_store,
                scope=scope,
                user_id=request.user_id,
                query=search.query,
                max_results=search.max_results,
            )
            added_resources.append(resource)
            search_summaries.append(
                {
                    "provider": search.provider,
                    "query": _safe_gmail_query(search.query),
                    "added_count": 1,
                }
            )
            continue

        resources = _add_drive_discovery_results(
            metadata_store=metadata_store,
            scope=scope,
            user_id=request.user_id,
            provider=search.provider,
            query=search.query,
            max_results=search.max_results,
        )
        added_resources.extend(resources)
        search_summaries.append(
            {
                "provider": search.provider,
                "query": search.query,
                "added_count": len(resources),
            }
        )

    response = {
        "status": "selected",
        "scope": scope,
        "plan": [search.model_dump() for search in plan.searches],
        "searches": search_summaries,
        "added_resources": added_resources,
    }

    if request.auto_ingest:
        background_tasks.add_task(_ingest_scope_resources, request.user_id)
        response["status"] = "queued"
        response["ingest"] = "queued"

    return response
