from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from app.sync.drive_sync import DriveSyncService


router = APIRouter(prefix="/drive", tags=["google-drive"])


def run_drive_sync(user_id: str, mode: str) -> None:
    service = DriveSyncService(user_id=user_id)
    if mode == "initial":
        jobs = service.initial_sync()
    elif mode == "incremental":
        jobs = service.incremental_sync()
    else:
        raise ValueError("mode must be 'initial' or 'incremental'")

    service.run_queued_jobs(jobs)


@router.get("/files")
def list_drive_files(user_id: str = Query(...)):
    try:
        files = DriveSyncService(user_id=user_id).list_supported_files()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "user_id": user_id,
        "supported_files": files,
        "count": len(files),
    }


@router.post("/sync")
def sync_drive(
    background_tasks: BackgroundTasks,
    user_id: str = Query(...),
    mode: str = Query("incremental", pattern="^(initial|incremental)$"),
    background: bool = Query(True),
):
    if background:
        background_tasks.add_task(run_drive_sync, user_id, mode)
        return {
            "user_id": user_id,
            "mode": mode,
            "status": "queued",
        }

    try:
        service = DriveSyncService(user_id=user_id)
        jobs = (
            service.initial_sync()
            if mode == "initial"
            else service.incremental_sync()
        )
        service.run_queued_jobs(jobs)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "user_id": user_id,
        "mode": mode,
        "status": "completed",
        "queued_jobs": jobs,
        "job_count": len(jobs),
    }
