import base64
import re
from email.message import EmailMessage
from html.parser import HTMLParser

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


class _HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self.parts.append(text)

    def text(self) -> str:
        return "\n".join(self.parts)


class GmailConnector:
    def __init__(self, credentials: Credentials):
        self.gmail = build("gmail", "v1", credentials=credentials)

    def get_profile(self) -> dict:
        return self.gmail.users().getProfile(userId="me").execute()

    def list_labels(self) -> list[dict]:
        result = self.gmail.users().labels().list(userId="me").execute()
        return result.get("labels", [])

    def list_messages(
        self,
        query: str = "",
        max_results: int = 20,
        label_ids: list[str] | None = None,
        page_token: str | None = None,
    ) -> dict:
        params = {
            "userId": "me",
            "maxResults": max_results,
            "q": query,
        }
        if label_ids:
            params["labelIds"] = label_ids
        if page_token:
            params["pageToken"] = page_token

        return self.gmail.users().messages().list(**params).execute()

    def get_message_metadata(self, message_id: str) -> dict:
        return self.gmail.users().messages().get(
            userId="me",
            id=message_id,
            format="metadata",
            metadataHeaders=[
                "From",
                "To",
                "Cc",
                "Subject",
                "Date",
                "Message-ID",
            ],
        ).execute()

    def search_message_metadata(
        self,
        query: str,
        max_results: int = 10,
        label_ids: list[str] | None = None,
    ) -> list[dict]:
        result = self.list_messages(
            query=query,
            max_results=max_results,
            label_ids=label_ids,
        )
        messages = []
        for message in result.get("messages", []):
            messages.append(self.get_message_metadata(message["id"]))
        return messages

    def get_message_full(self, message_id: str) -> dict:
        return self.gmail.users().messages().get(
            userId="me",
            id=message_id,
            format="full",
        ).execute()

    def get_thread(self, thread_id: str) -> dict:
        return self.gmail.users().threads().get(
            userId="me",
            id=thread_id,
            format="full",
        ).execute()

    def create_draft(
        self,
        to: list[str],
        subject: str,
        body: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        thread_id: str | None = None,
    ) -> dict:
        message = self._build_raw_message(
            to=to,
            subject=subject,
            body=body,
            cc=cc,
            bcc=bcc,
        )
        draft_body = {"message": {"raw": message}}
        if thread_id:
            draft_body["message"]["threadId"] = thread_id
        return self.gmail.users().drafts().create(
            userId="me",
            body=draft_body,
        ).execute()

    def send_message(
        self,
        to: list[str],
        subject: str,
        body: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        thread_id: str | None = None,
    ) -> dict:
        message_body = {
            "raw": self._build_raw_message(
                to=to,
                subject=subject,
                body=body,
                cc=cc,
                bcc=bcc,
            )
        }
        if thread_id:
            message_body["threadId"] = thread_id
        return self.gmail.users().messages().send(
            userId="me",
            body=message_body,
        ).execute()

    def _build_raw_message(
        self,
        to: list[str],
        subject: str,
        body: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
    ) -> str:
        message = EmailMessage()
        message["To"] = ", ".join(to)
        if cc:
            message["Cc"] = ", ".join(cc)
        if bcc:
            message["Bcc"] = ", ".join(bcc)
        message["Subject"] = subject
        message.set_content(body)
        return base64.urlsafe_b64encode(message.as_bytes()).decode()

    def list_history(
        self,
        start_history_id: str,
        page_token: str | None = None,
    ) -> dict:
        params = {
            "userId": "me",
            "startHistoryId": start_history_id,
            "historyTypes": [
                "messageAdded",
                "messageDeleted",
                "labelAdded",
                "labelRemoved",
            ],
        }
        if page_token:
            params["pageToken"] = page_token

        return self.gmail.users().history().list(**params).execute()

    def watch_mailbox(
        self,
        topic_name: str,
        label_ids: list[str] | None = None,
    ) -> dict:
        body = {"topicName": topic_name}
        if label_ids:
            body["labelIds"] = label_ids
            body["labelFilterBehavior"] = "INCLUDE"

        return self.gmail.users().watch(userId="me", body=body).execute()

    def stop_watch(self) -> dict:
        return self.gmail.users().stop(userId="me").execute()

    def extract_headers(self, message: dict) -> dict:
        headers = message.get("payload", {}).get("headers", [])
        header_map = {
            header.get("name", "").lower(): header.get("value")
            for header in headers
        }

        return {
            "from": header_map.get("from"),
            "to": header_map.get("to"),
            "cc": header_map.get("cc"),
            "subject": header_map.get("subject"),
            "date": header_map.get("date"),
            "message_id_header": header_map.get("message-id"),
        }

    def extract_plain_text(self, message: dict) -> str:
        payload = message.get("payload", {})
        return self._extract_text_from_payload(payload).strip()

    def _extract_text_from_payload(self, payload: dict) -> str:
        mime_type = payload.get("mimeType", "")

        if mime_type == "text/plain":
            return self._decode_base64url(payload.get("body", {}).get("data"))

        if mime_type == "text/html":
            html = self._decode_base64url(payload.get("body", {}).get("data"))
            return self._strip_html(html)

        collected = []
        for part in payload.get("parts", []):
            filename = part.get("filename")
            if filename:
                continue

            text = self._extract_text_from_payload(part)
            if text:
                collected.append(text)

        return "\n\n".join(collected)

    def _decode_base64url(self, data: str | None) -> str:
        if not data:
            return ""

        decoded = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
        return decoded.decode("utf-8", errors="ignore")

    def _strip_html(self, html: str) -> str:
        parser = _HTMLTextExtractor()
        parser.feed(html)
        text = parser.text()
        return re.sub(r"\n{3,}", "\n\n", text)
