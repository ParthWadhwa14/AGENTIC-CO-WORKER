from pathlib import Path

from app.config import settings
from app.connectors.google_drive import (
    GOOGLE_DOC_MIME_TYPE,
    GOOGLE_SHEET_MIME_TYPE,
    SUPPORTED_BINARY_MIME_TYPES,
    SUPPORTED_GOOGLE_MIME_TYPES,
    GoogleDriveConnector,
)
from app.services.ingestion_jobs import process_ingestion_job
from app.services.tokens import GOOGLE_DRIVE_PROVIDER, GoogleCredentialStore
from app.storage.metadata_store import MetadataStore


class DriveSyncService:
    def __init__(
        self,
        user_id: str,
        metadata_store: MetadataStore | None = None,
        credential_store: GoogleCredentialStore | None = None,
    ):
        self.user_id = user_id
        self.metadata_store = metadata_store or MetadataStore()
        self.credential_store = credential_store or GoogleCredentialStore(
            metadata_store=self.metadata_store
        )
        self.drive = GoogleDriveConnector(
            self.credential_store.get_credentials(
                user_id,
                provider=GOOGLE_DRIVE_PROVIDER,
            )
        )

    def list_supported_files(self, page_size: int = 50) -> list[dict]:
        files: list[dict] = []
        page_token = None

        while True:
            result = self.drive.list_files(
                page_size=page_size,
                page_token=page_token,
            )
            files.extend(
                file for file in result.get("files", [])
                if self.is_supported(file)
            )
            page_token = result.get("nextPageToken")
            if not page_token:
                break

        return files

    def initial_sync(self) -> list[dict]:
        queued_jobs = []

        for file in self.list_supported_files(page_size=100):
            job = self.queue_file_for_ingestion(file, reason="drive_initial_sync")
            if job:
                queued_jobs.append(job)

        start_page_token = self.drive.get_start_page_token()
        self.metadata_store.upsert_drive_sync_state(
            self.user_id,
            start_page_token=start_page_token,
        )

        return queued_jobs

    def incremental_sync(self) -> list[dict]:
        state = self.metadata_store.get_drive_sync_state(self.user_id)
        if not state or not state.get("start_page_token"):
            return self.initial_sync()

        queued_jobs = []
        page_token = state["start_page_token"]
        new_start_page_token = None

        while page_token:
            result = self.drive.list_changes(page_token)
            for change in result.get("changes", []):
                file = change.get("file")
                if change.get("removed") or not file or file.get("trashed"):
                    continue

                if not self.is_supported(file):
                    continue

                job = self.queue_file_for_ingestion(
                    file,
                    reason="drive_incremental_sync",
                )
                if job:
                    queued_jobs.append(job)

            page_token = result.get("nextPageToken")
            new_start_page_token = result.get("newStartPageToken")

        if new_start_page_token:
            self.metadata_store.upsert_drive_sync_state(
                self.user_id,
                start_page_token=new_start_page_token,
            )

        return queued_jobs

    def run_queued_jobs(self, queued_jobs: list[dict]) -> None:
        for job in queued_jobs:
            process_ingestion_job(
                job["job_id"],
                job["document_id"],
                job["local_path"],
                metadata_store=self.metadata_store,
            )

    def queue_file_for_ingestion(self, file: dict, reason: str) -> dict | None:
        mime_type = file.get("mimeType")
        if mime_type in {
            GOOGLE_SHEET_MIME_TYPE,
            "text/csv",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }:
            document_id, _ = self.metadata_store.upsert_drive_document(
                user_id=self.user_id,
                file=file,
                local_path=None,
                index_status="table_source",
            )
            return {
                "job_id": None,
                "document_id": document_id,
                "file_id": file["id"],
                "file_name": file.get("name"),
                "mime_type": mime_type,
                "local_path": None,
                "reason": "table_source_not_vectorized",
                "status": "table_source",
            }

        local_path = self.download_or_export(file)
        document_id, is_changed = self.metadata_store.upsert_drive_document(
            user_id=self.user_id,
            file=file,
            local_path=local_path,
            index_status="queued",
        )

        if not is_changed:
            self.metadata_store.update_document_status(
                document_id,
                index_status="indexed",
                local_path=local_path,
            )
            return None

        job_id = self.metadata_store.create_ingestion_job(
            user_id=self.user_id,
            document_id=document_id,
            reason=reason,
        )

        return {
            "job_id": job_id,
            "document_id": document_id,
            "file_id": file["id"],
            "file_name": file.get("name"),
            "mime_type": file.get("mimeType"),
            "local_path": local_path,
            "reason": reason,
        }

    def is_supported(self, file: dict) -> bool:
        mime_type = file.get("mimeType")
        return (
            mime_type in SUPPORTED_BINARY_MIME_TYPES
            or mime_type in SUPPORTED_GOOGLE_MIME_TYPES
        )

    def download_or_export(self, file: dict) -> str:
        file_id = file["id"]
        mime_type = file.get("mimeType")
        safe_name = self.safe_name(file.get("name") or file_id)
        output_path = settings.DRIVE_DOWNLOAD_DIR / self.user_id / f"{file_id}_{safe_name}"
        if mime_type == GOOGLE_DOC_MIME_TYPE:
            output_path = output_path.with_suffix(".txt")
            return self.drive.export_google_doc(file_id, str(output_path))

        if mime_type == GOOGLE_SHEET_MIME_TYPE:
            output_path = output_path.with_suffix(".xlsx")
            return self.drive.export_google_sheet_as_xlsx(file_id, str(output_path))

        return self.drive.download_binary_file(file_id, str(output_path))

    def safe_name(self, name: str) -> str:
        return Path(name).name.replace("/", "_").replace("\\", "_")
