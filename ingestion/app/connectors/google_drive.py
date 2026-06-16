import io
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload


GOOGLE_DOC_MIME_TYPE = "application/vnd.google-apps.document"
GOOGLE_SHEET_MIME_TYPE = "application/vnd.google-apps.spreadsheet"

SUPPORTED_GOOGLE_MIME_TYPES = {
    GOOGLE_DOC_MIME_TYPE: "google_doc",
    GOOGLE_SHEET_MIME_TYPE: "google_sheet",
}

SUPPORTED_BINARY_MIME_TYPES = {
    "application/pdf": "pdf",
    "text/plain": "txt",
    "text/csv": "csv",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
}


class GoogleDriveConnector:
    def __init__(self, credentials: Credentials):
        self.drive = build("drive", "v3", credentials=credentials)

    def list_files(
        self,
        page_size: int = 50,
        page_token: str | None = None,
    ) -> dict:
        return self.drive.files().list(
            pageSize=page_size,
            pageToken=page_token,
            q="trashed=false",
            fields=(
                "nextPageToken, files("
                "id, name, mimeType, modifiedTime, webViewLink, size, md5Checksum)"
            ),
        ).execute()

    def search_files(self, query: str, page_size: int = 20) -> list[dict]:
        safe_query = query.replace("\\", "\\\\").replace("'", "\\'")
        results = self.drive.files().list(
            pageSize=page_size,
            q=f"trashed=false and fullText contains '{safe_query}'",
            fields=(
                "files(id, name, mimeType, modifiedTime, webViewLink, size, md5Checksum)"
            ),
        ).execute()
        return results.get("files", [])

    def discover_files(
        self,
        query: str = "",
        mime_type: str | None = None,
        page_size: int = 25,
        page_token: str | None = None,
    ) -> dict:
        filters = ["trashed=false"]
        if query:
            safe_query = query.replace("\\", "\\\\").replace("'", "\\'")
            filters.append(
                f"(name contains '{safe_query}' or fullText contains '{safe_query}')"
            )
        if mime_type:
            filters.append(f"mimeType='{mime_type}'")

        return self.drive.files().list(
            pageSize=page_size,
            pageToken=page_token,
            q=" and ".join(filters),
            fields=(
                "nextPageToken, files("
                "id, name, mimeType, modifiedTime, webViewLink, size, "
                "md5Checksum, parents)"
            ),
        ).execute()

    def list_folders(
        self,
        page_size: int = 50,
        page_token: str | None = None,
    ) -> dict:
        return self.drive.files().list(
            pageSize=page_size,
            pageToken=page_token,
            q=(
                "mimeType='application/vnd.google-apps.folder' "
                "and trashed=false"
            ),
            fields=(
                "nextPageToken, files("
                "id, name, mimeType, modifiedTime, webViewLink, parents)"
            ),
        ).execute()

    def list_folder_children(
        self,
        folder_id: str,
        page_size: int = 50,
        page_token: str | None = None,
    ) -> dict:
        safe_folder_id = folder_id.replace("\\", "\\\\").replace("'", "\\'")
        return self.drive.files().list(
            pageSize=page_size,
            pageToken=page_token,
            q=f"'{safe_folder_id}' in parents and trashed=false",
            fields=(
                "nextPageToken, files("
                "id, name, mimeType, modifiedTime, webViewLink, size, "
                "md5Checksum, parents)"
            ),
        ).execute()

    def get_start_page_token(self) -> str:
        result = self.drive.changes().getStartPageToken().execute()
        return result["startPageToken"]

    def list_changes(self, page_token: str) -> dict:
        return self.drive.changes().list(
            pageToken=page_token,
            spaces="drive",
            fields=(
                "newStartPageToken,nextPageToken,changes("
                "removed,fileId,file("
                "id,name,mimeType,modifiedTime,webViewLink,size,md5Checksum,trashed))"
            ),
        ).execute()

    def download_binary_file(self, file_id: str, output_path: str) -> str:
        request = self.drive.files().get_media(fileId=file_id)
        return self._download(request, output_path)

    def export_google_doc(self, file_id: str, output_path: str) -> str:
        request = self.drive.files().export_media(
            fileId=file_id,
            mimeType="text/plain",
        )
        return self._download(request, output_path)

    def export_google_sheet_as_xlsx(self, file_id: str, output_path: str) -> str:
        request = self.drive.files().export_media(
            fileId=file_id,
            mimeType=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
        )
        return self._download(request, output_path)

    def _download(self, request, output_path: str) -> str:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with io.FileIO(path, "wb") as handle:
            downloader = MediaIoBaseDownload(handle, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()

        return str(path)
