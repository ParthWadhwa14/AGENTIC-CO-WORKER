import re
from typing import Any
from pathlib import Path

from app.connectors.gmail_connector import GmailConnector
from app.connectors.google_docs import GoogleDocsConnector
from app.connectors.google_sheets import GoogleSheetsConnector
from app.services.tokens import (
    GOOGLE_DRIVE_PROVIDER,
    GOOGLE_GMAIL_PROVIDER,
    GoogleCredentialStore,
)


ALLOWED_ACTION_TYPES = {
    "create_gmail_draft",
    "send_gmail",
    "create_google_doc",
    "update_google_doc",
    "create_google_sheet",
    "update_google_sheet",
}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_EMAIL_RECIPIENTS = 10
MAX_EMAIL_BODY_CHARS = 12000
MAX_DOC_TEXT_CHARS = 50000
MAX_SHEET_CELLS = 500
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
MAX_ATTACHMENTS = 5


class ActionGuardrailError(ValueError):
    pass


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


def _require_string(payload: dict, key: str, max_length: int | None = None) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ActionGuardrailError(f"Missing required field: {key}")
    value = value.strip()
    if max_length and len(value) > max_length:
        raise ActionGuardrailError(f"{key} is too long.")
    return value


def _validate_recipients(payload: dict) -> tuple[list[str], list[str], list[str]]:
    to = _as_list(payload.get("to"))
    cc = _as_list(payload.get("cc"))
    bcc = _as_list(payload.get("bcc"))
    recipients = to + cc + bcc
    if not to:
        raise ActionGuardrailError("At least one email recipient is required.")
    if len(recipients) > MAX_EMAIL_RECIPIENTS:
        raise ActionGuardrailError(
            f"Too many recipients. Limit is {MAX_EMAIL_RECIPIENTS}."
        )
    invalid = [email for email in recipients if not EMAIL_RE.match(email)]
    if invalid:
        raise ActionGuardrailError(f"Invalid recipient address: {invalid[0]}")
    return to, cc, bcc


def _validate_attachments(payload: dict) -> list[dict]:
    attachments = payload.get("attachments") or []
    if not isinstance(attachments, list):
        raise ActionGuardrailError("Attachments must be a list.")
    if len(attachments) > MAX_ATTACHMENTS:
        raise ActionGuardrailError(f"Too many attachments. Limit is {MAX_ATTACHMENTS}.")

    validated = []
    for attachment in attachments:
        if not isinstance(attachment, dict):
            raise ActionGuardrailError("Attachment entries must be objects.")
        local_path = attachment.get("local_path")
        if not isinstance(local_path, str) or not local_path.strip():
            raise ActionGuardrailError("Attachment is missing local_path.")
        path = Path(local_path)
        if not path.is_file():
            raise ActionGuardrailError(f"Attachment file not found: {path.name}")
        if path.stat().st_size > MAX_ATTACHMENT_BYTES:
            raise ActionGuardrailError(f"Attachment is too large: {path.name}")
        validated.append(
            {
                "document_id": attachment.get("document_id"),
                "local_path": str(path),
                "filename": attachment.get("filename") or path.name,
                "mime_type": attachment.get("mime_type") or "application/octet-stream",
            }
        )
    return validated


def _validate_sheet_values(values: Any) -> list[list[str]]:
    if not isinstance(values, list) or not values:
        raise ActionGuardrailError("Sheet values must be a non-empty 2D array.")
    normalized = []
    cell_count = 0
    for row in values:
        if not isinstance(row, list):
            raise ActionGuardrailError("Sheet values must be a 2D array.")
        normalized_row = ["" if cell is None else str(cell) for cell in row]
        cell_count += len(normalized_row)
        normalized.append(normalized_row)
    if cell_count > MAX_SHEET_CELLS:
        raise ActionGuardrailError(f"Too many sheet cells. Limit is {MAX_SHEET_CELLS}.")
    return normalized


def validate_action(action: dict) -> dict:
    action_type = action.get("action_type")
    payload = action.get("payload") or {}
    if action_type not in ALLOWED_ACTION_TYPES:
        raise ActionGuardrailError("Unsupported or unsafe action type.")
    if not isinstance(payload, dict):
        raise ActionGuardrailError("Action payload must be an object.")

    if action_type in {"create_gmail_draft", "send_gmail"}:
        draft_id = payload.get("draft_id")
        if action_type == "send_gmail" and isinstance(draft_id, str) and draft_id.strip():
            return {
                **action,
                "payload": {
                    **payload,
                    "draft_id": draft_id.strip(),
                },
            }
        to, cc, bcc = _validate_recipients(payload)
        attachments = _validate_attachments(payload)
        if payload.get("attachments_required") and not attachments:
            raise ActionGuardrailError(
                "Requested attachment could not be resolved to an uploaded local file."
            )
        return {
            **action,
            "payload": {
                **payload,
                "to": to,
                "cc": cc,
                "bcc": bcc,
                "subject": _require_string(payload, "subject", max_length=300),
                "body": _require_string(
                    payload,
                    "body",
                    max_length=MAX_EMAIL_BODY_CHARS,
                ),
                "attachments": attachments,
            },
        }

    if action_type == "create_google_doc":
        return {
            **action,
            "payload": {
                **payload,
                "title": _require_string(payload, "title", max_length=300),
                "text": _require_string(payload, "text", max_length=MAX_DOC_TEXT_CHARS),
            },
        }

    if action_type == "update_google_doc":
        document_id = _require_string(payload, "document_id", max_length=300)
        operation = payload.get("operation", "append_text")
        if operation not in {"append_text", "replace_text"}:
            raise ActionGuardrailError("Docs update operation must be append_text or replace_text.")
        validated = {
            **payload,
            "document_id": document_id,
            "operation": operation,
        }
        if operation == "append_text":
            validated["text"] = _require_string(
                payload,
                "text",
                max_length=MAX_DOC_TEXT_CHARS,
            )
        else:
            validated["contains_text"] = _require_string(payload, "contains_text")
            validated["replace_text"] = _require_string(
                payload,
                "replace_text",
                max_length=MAX_DOC_TEXT_CHARS,
            )
        return {**action, "payload": validated}

    if action_type == "create_google_sheet":
        payload = {
            **payload,
            "title": _require_string(payload, "title", max_length=300),
        }
        if payload.get("values"):
            payload["values"] = _validate_sheet_values(payload["values"])
            payload["range"] = payload.get("range") or "Sheet1!A1"
        return {**action, "payload": payload}

    if action_type == "update_google_sheet":
        operation = payload.get("operation", "update_values")
        if operation not in {"update_values", "append_values"}:
            raise ActionGuardrailError(
                "Sheets update operation must be update_values or append_values."
            )
        return {
            **action,
            "payload": {
                **payload,
                "spreadsheet_id": _require_string(payload, "spreadsheet_id"),
                "range": _require_string(payload, "range", max_length=300),
                "operation": operation,
                "values": _validate_sheet_values(payload.get("values")),
            },
        }

    raise ActionGuardrailError("Unsupported action.")


def execute_action(user_id: str, action: dict) -> dict:
    action = validate_action(action)
    action_type = action["action_type"]
    payload = action["payload"]
    credential_store = GoogleCredentialStore()

    if action_type in {"create_gmail_draft", "send_gmail"}:
        gmail = GmailConnector(
            credential_store.get_credentials(user_id, provider=GOOGLE_GMAIL_PROVIDER)
        )
        if action_type == "create_gmail_draft":
            result = gmail.create_draft(
                to=payload["to"],
                cc=payload.get("cc"),
                bcc=payload.get("bcc"),
                subject=payload["subject"],
                body=payload["body"],
                thread_id=payload.get("thread_id"),
                attachments=payload.get("attachments"),
            )
        else:
            if payload.get("draft_id"):
                result = gmail.send_draft(payload["draft_id"])
            else:
                result = gmail.send_message(
                    to=payload["to"],
                    cc=payload.get("cc"),
                    bcc=payload.get("bcc"),
                    subject=payload["subject"],
                    body=payload["body"],
                    thread_id=payload.get("thread_id"),
                    attachments=payload.get("attachments"),
                )
        if action_type == "create_gmail_draft" and not result.get("id"):
            raise ActionGuardrailError("Gmail draft API did not return a draft id.")
        if action_type == "send_gmail" and not result.get("id"):
            raise ActionGuardrailError("Gmail send API did not return a sent message id.")
        return {
            "status": "executed",
            "action_type": action_type,
            "payload": payload,
            "result": result,
        }

    if action_type in {"create_google_doc", "update_google_doc"}:
        docs = GoogleDocsConnector(
            credential_store.get_credentials(user_id, provider=GOOGLE_DRIVE_PROVIDER)
        )
        if action_type == "create_google_doc":
            document = docs.create_document(payload["title"])
            if not document.get("documentId"):
                raise ActionGuardrailError("Google Docs API did not return a document id.")
            docs.insert_text(document["documentId"], payload["text"])
            document["documentUrl"] = (
                f"https://docs.google.com/document/d/{document['documentId']}/edit"
            )
            result = document
        elif payload["operation"] == "append_text":
            result = docs.append_text(payload["document_id"], payload["text"])
        else:
            result = docs.replace_all_text(
                payload["document_id"],
                contains_text=payload["contains_text"],
                replace_text=payload["replace_text"],
            )
        return {
            "status": "executed",
            "action_type": action_type,
            "payload": payload,
            "result": result,
        }

    if action_type in {"create_google_sheet", "update_google_sheet"}:
        sheets = GoogleSheetsConnector(
            credential_store.get_credentials(user_id, provider=GOOGLE_DRIVE_PROVIDER)
        )
        if action_type == "create_google_sheet":
            result = sheets.create_spreadsheet(payload["title"])
            if not result.get("spreadsheetId"):
                raise ActionGuardrailError("Google Sheets API did not return a spreadsheet id.")
            if payload.get("values"):
                sheets.update_values(
                    result["spreadsheetId"],
                    payload["range"],
                    payload["values"],
                )
        elif payload["operation"] == "append_values":
            result = sheets.append_values(
                payload["spreadsheet_id"],
                payload["range"],
                payload["values"],
            )
        else:
            result = sheets.update_values(
                payload["spreadsheet_id"],
                payload["range"],
                payload["values"],
            )
        if action_type == "update_google_sheet" and not (
            result.get("updatedCells") or result.get("updates", {}).get("updatedCells")
        ):
            raise ActionGuardrailError("Google Sheets API did not report updated cells.")
        return {
            "status": "executed",
            "action_type": action_type,
            "payload": payload,
            "result": result,
        }

    raise ActionGuardrailError("Unsupported action.")
