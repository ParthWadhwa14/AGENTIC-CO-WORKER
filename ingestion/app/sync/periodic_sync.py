from app.services.tokens import (
    GOOGLE_DRIVE_PROVIDER,
    GOOGLE_GMAIL_PROVIDER,
    GOOGLE_PROVIDER,
)
from app.storage.metadata_store import MetadataStore
from app.sync.drive_sync import DriveSyncService
from app.sync.gmail_sync import GmailSyncService


def sync_all_connected_accounts() -> dict:
    metadata_store = MetadataStore()
    results = {
        "drive": [],
        "gmail": [],
    }

    drive_accounts = {
        account["user_id"]: account
        for provider in [GOOGLE_DRIVE_PROVIDER, GOOGLE_PROVIDER, "google"]
        for account in metadata_store.list_connected_accounts(provider=provider)
    }
    gmail_accounts = {
        account["user_id"]: account
        for provider in [GOOGLE_GMAIL_PROVIDER, GOOGLE_PROVIDER, "google"]
        for account in metadata_store.list_connected_accounts(provider=provider)
    }

    for account in drive_accounts.values():
        user_id = account["user_id"]
        try:
            service = DriveSyncService(
                user_id=user_id,
                metadata_store=metadata_store,
            )
            jobs = service.incremental_sync()
            service.run_queued_jobs(jobs)
            results["drive"].append(
                {
                    "user_id": user_id,
                    "status": "synced",
                    "jobs": len(jobs),
                }
            )
        except Exception as exc:
            results["drive"].append(
                {
                    "user_id": user_id,
                    "status": "failed",
                    "error": str(exc),
                }
            )

    for account in gmail_accounts.values():
        user_id = account["user_id"]
        try:
            result = GmailSyncService(
                user_id=user_id,
                metadata_store=metadata_store,
            ).partial_sync()
            results["gmail"].append(
                {
                    "user_id": user_id,
                    "status": "synced",
                    "result": result,
                }
            )
        except Exception as exc:
            results["gmail"].append(
                {
                    "user_id": user_id,
                    "status": "failed",
                    "error": str(exc),
                }
            )

    return results
