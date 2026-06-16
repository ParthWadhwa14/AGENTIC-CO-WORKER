from fastapi import APIRouter, BackgroundTasks, Query

from app.sync.periodic_sync import sync_all_connected_accounts


router = APIRouter(prefix="/sync", tags=["sync"])


@router.post("/all")
def sync_all(
    background_tasks: BackgroundTasks,
    background: bool = Query(True),
):
    if background:
        background_tasks.add_task(sync_all_connected_accounts)
        return {"status": "queued"}

    return {
        "status": "completed",
        "result": sync_all_connected_accounts(),
    }
