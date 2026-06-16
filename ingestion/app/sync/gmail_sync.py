from app.chunking import chunk_text_elements
from app.connectors.gmail_connector import GmailConnector
from app.loaders.gmail_loader import GmailMessageLoader
from app.qdrant_store import QdrantStore
from app.services.tokens import GOOGLE_GMAIL_PROVIDER, GoogleCredentialStore
from app.storage.metadata_store import MetadataStore, utc_now


DEFAULT_GMAIL_QUERY = "newer_than:180d -in:spam -in:trash"
GMAIL_CHUNK_SIZE = 800
GMAIL_CHUNK_OVERLAP = 120


class GmailSyncService:
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
        self.gmail = GmailConnector(
            self.credential_store.get_credentials(
                user_id,
                provider=GOOGLE_GMAIL_PROVIDER,
            )
        )
        self.loader = GmailMessageLoader()
        self.qdrant = QdrantStore()

    def initial_sync(
        self,
        query: str = DEFAULT_GMAIL_QUERY,
        max_messages: int = 100,
        label_ids: list[str] | None = None,
    ) -> dict:
        synced = 0
        skipped = 0
        page_token = None

        while synced + skipped < max_messages:
            result = self.gmail.list_messages(
                query=query,
                max_results=min(50, max_messages - synced - skipped),
                label_ids=label_ids,
                page_token=page_token,
            )
            messages = result.get("messages", [])
            if not messages:
                break

            for message_ref in messages:
                if synced + skipped >= max_messages:
                    break

                outcome = self.index_message(message_ref["id"])
                if outcome["status"] == "indexed":
                    synced += 1
                else:
                    skipped += 1

            page_token = result.get("nextPageToken")
            if not page_token:
                break

        profile = self.gmail.get_profile()
        self.metadata_store.upsert_gmail_sync_state(
            user_id=self.user_id,
            email_address=profile.get("emailAddress"),
            last_history_id=profile.get("historyId"),
            full_sync=True,
        )

        return {
            "user_id": self.user_id,
            "email": profile.get("emailAddress"),
            "history_id": profile.get("historyId"),
            "synced_messages": synced,
            "skipped_messages": skipped,
            "query": query,
            "label_ids": label_ids or [],
            "max_messages": max_messages,
        }

    def partial_sync(self) -> dict:
        state = self.metadata_store.get_gmail_sync_state(self.user_id)
        if not state or not state.get("last_history_id"):
            return self.initial_sync()

        changed_message_ids: set[str] = set()
        deleted_message_ids: set[str] = set()
        page_token = None
        latest_history_id = state["last_history_id"]

        while True:
            result = self.gmail.list_history(
                start_history_id=state["last_history_id"],
                page_token=page_token,
            )
            latest_history_id = result.get("historyId", latest_history_id)

            for history_item in result.get("history", []):
                for added in history_item.get("messagesAdded", []):
                    changed_message_ids.add(added["message"]["id"])

                for deleted in history_item.get("messagesDeleted", []):
                    deleted_message_ids.add(deleted["message"]["id"])

                for label_added in history_item.get("labelsAdded", []):
                    changed_message_ids.add(label_added["message"]["id"])

                for label_removed in history_item.get("labelsRemoved", []):
                    changed_message_ids.add(label_removed["message"]["id"])

            page_token = result.get("nextPageToken")
            if not page_token:
                break

        deleted_documents = []
        for message_id in deleted_message_ids:
            document_id = self.metadata_store.mark_gmail_message_deleted(
                self.user_id,
                message_id,
            )
            if document_id:
                self.qdrant.delete_document_chunks(document_id)
                deleted_documents.append(document_id)

        indexed = 0
        skipped = 0
        for message_id in sorted(changed_message_ids - deleted_message_ids):
            outcome = self.index_message(message_id)
            if outcome["status"] == "indexed":
                indexed += 1
            else:
                skipped += 1

        profile = self.gmail.get_profile()
        self.metadata_store.upsert_gmail_sync_state(
            user_id=self.user_id,
            email_address=profile.get("emailAddress"),
            last_history_id=latest_history_id,
            partial_sync=True,
        )

        return {
            "user_id": self.user_id,
            "latest_history_id": latest_history_id,
            "changed_messages": len(changed_message_ids),
            "deleted_messages": len(deleted_message_ids),
            "deleted_documents": deleted_documents,
            "indexed_messages": indexed,
            "skipped_messages": skipped,
        }

    def index_message(self, message_id: str) -> dict:
        message = self.gmail.get_message_full(message_id)
        headers = self.gmail.extract_headers(message)
        body_text = self.gmail.extract_plain_text(message)

        if not body_text.strip():
            return {
                "message_id": message_id,
                "status": "skipped",
                "reason": "empty_body",
            }

        document_id, is_changed = self.metadata_store.upsert_gmail_message(
            user_id=self.user_id,
            message=message,
            headers=headers,
            body_text=body_text,
        )

        if not is_changed:
            return {
                "message_id": message_id,
                "document_id": document_id,
                "status": "skipped",
                "reason": "unchanged",
            }

        elements = self.loader.load_message(
            message=message,
            body_text=body_text,
            headers=headers,
            document_id=document_id,
        )
        chunks = chunk_text_elements(
            elements,
            chunk_size=GMAIL_CHUNK_SIZE,
            chunk_overlap=GMAIL_CHUNK_OVERLAP,
        )

        self.qdrant.delete_document_chunks(document_id)
        self.qdrant.upsert_chunks(chunks)
        self.metadata_store.mark_gmail_message_indexed(
            self.user_id,
            message_id,
        )
        self.metadata_store.update_document_status(
            document_id,
            index_status="indexed",
            indexed_at=utc_now(),
        )

        return {
            "message_id": message_id,
            "document_id": document_id,
            "status": "indexed",
            "chunks": len(chunks),
        }
