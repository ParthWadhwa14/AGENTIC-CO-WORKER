from uuid import uuid4

from app.models import ParsedElement


class GmailMessageLoader:
    source_type = "gmail"

    def load_message(
        self,
        message: dict,
        body_text: str,
        headers: dict,
        document_id: str | None = None,
    ) -> list[ParsedElement]:
        document_id = document_id or str(uuid4())
        subject = headers.get("subject") or "(no subject)"
        sender = headers.get("from") or ""
        recipient = headers.get("to") or ""
        cc = headers.get("cc") or ""
        date = headers.get("date") or ""

        text = f"""
Subject: {subject}
From: {sender}
To: {recipient}
Cc: {cc}
Date: {date}

Body:
{body_text}
""".strip()

        return [
            ParsedElement(
                document_id=document_id,
                source_type=self.source_type,
                file_name=f"gmail_{message.get('id')}",
                element_type="email_message",
                text=text,
                heading_path=[subject],
                metadata={
                    "gmail_message_id": message.get("id"),
                    "gmail_thread_id": message.get("threadId"),
                    "subject": subject,
                    "from": sender,
                    "to": recipient,
                    "cc": cc,
                    "date": date,
                    "message_id_header": headers.get("message_id_header"),
                    "snippet": message.get("snippet"),
                    "label_ids": message.get("labelIds", []),
                    "history_id": message.get("historyId"),
                    "internal_date": message.get("internalDate"),
                    "is_parent": False,
                },
            )
        ]
