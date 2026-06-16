from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


class GoogleDocsConnector:
    def __init__(self, credentials: Credentials):
        self.docs = build("docs", "v1", credentials=credentials)

    def get_document(self, document_id: str) -> dict:
        return self.docs.documents().get(documentId=document_id).execute()

    def create_document(self, title: str) -> dict:
        return self.docs.documents().create(
            body={"title": title}
        ).execute()

    def insert_text(self, document_id: str, text: str, index: int = 1) -> dict:
        requests = [
            {
                "insertText": {
                    "location": {"index": index},
                    "text": text,
                }
            }
        ]
        return self.docs.documents().batchUpdate(
            documentId=document_id,
            body={"requests": requests},
        ).execute()

    def append_text(self, document_id: str, text: str) -> dict:
        document = self.get_document(document_id)
        content = document.get("body", {}).get("content", [])
        end_index = 1
        if content:
            end_index = max(1, content[-1].get("endIndex", 2) - 1)
        return self.insert_text(document_id, text, index=end_index)

    def replace_all_text(
        self,
        document_id: str,
        contains_text: str,
        replace_text: str,
        match_case: bool = True,
    ) -> dict:
        requests = [
            {
                "replaceAllText": {
                    "containsText": {
                        "text": contains_text,
                        "matchCase": match_case,
                    },
                    "replaceText": replace_text,
                }
            }
        ]
        return self.docs.documents().batchUpdate(
            documentId=document_id,
            body={"requests": requests},
        ).execute()
