import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.config import settings


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MetadataStore:
    def __init__(self, database_url: str | None = None):
        self.database_url = database_url or settings.METADATA_DATABASE_URL
        self.db_path = self._sqlite_path(self.database_url)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def _sqlite_path(self, database_url: str) -> Path:
        if database_url.startswith("sqlite:///"):
            return Path(database_url.removeprefix("sqlite:///"))

        if "://" not in database_url:
            return Path(database_url)

        raise ValueError(
            "Only sqlite:// URLs are supported by MetadataStore for now. "
            "Use this class as the local MVP metadata store, then swap it "
            "for PostgreSQL when DATABASE_URL points to Postgres."
        )

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def init_db(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS connected_accounts (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    service TEXT,
                    access_token_encrypted TEXT NOT NULL,
                    refresh_token_encrypted TEXT,
                    scopes TEXT,
                    expires_at TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, provider)
                );

                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    external_id TEXT,
                    file_name TEXT NOT NULL,
                    mime_type TEXT,
                    web_url TEXT,
                    local_path TEXT,
                    storage_bucket TEXT,
                    storage_path TEXT,
                    checksum TEXT,
                    modified_at TEXT,
                    indexed_at TEXT,
                    index_status TEXT DEFAULT 'pending',
                    error TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, source, external_id)
                );

                CREATE TABLE IF NOT EXISTS ingestion_jobs (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    document_id TEXT NOT NULL REFERENCES documents(id),
                    status TEXT DEFAULT 'queued',
                    reason TEXT,
                    error TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    started_at TEXT,
                    finished_at TEXT
                );

                CREATE TABLE IF NOT EXISTS drive_sync_state (
                    user_id TEXT PRIMARY KEY,
                    start_page_token TEXT,
                    channel_id TEXT,
                    resource_id TEXT,
                    channel_expiration TEXT,
                    last_synced_at TEXT
                );

                CREATE TABLE IF NOT EXISTS gmail_messages (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL REFERENCES documents(id),
                    user_id TEXT NOT NULL,
                    gmail_message_id TEXT NOT NULL,
                    gmail_thread_id TEXT,
                    subject TEXT,
                    sender TEXT,
                    recipient TEXT,
                    snippet TEXT,
                    internal_date TEXT,
                    history_id TEXT,
                    labels TEXT,
                    indexed_at TEXT,
                    deleted_at TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, gmail_message_id)
                );

                CREATE TABLE IF NOT EXISTS gmail_sync_state (
                    user_id TEXT PRIMARY KEY,
                    email_address TEXT,
                    last_history_id TEXT,
                    last_full_sync_at TEXT,
                    last_partial_sync_at TEXT,
                    watch_expiration TEXT,
                    pubsub_topic TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS oauth_states (
                    state TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    scopes TEXT,
                    code_verifier TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS agent_profiles (
                    user_id TEXT PRIMARY KEY,
                    agent_description TEXT,
                    user_context TEXT,
                    response_preferences TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS knowledge_scopes (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT,
                    is_default INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS scope_resources (
                    id TEXT PRIMARY KEY,
                    scope_id TEXT NOT NULL REFERENCES knowledge_scopes(id)
                        ON DELETE CASCADE,
                    user_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    resource_type TEXT NOT NULL,
                    external_id TEXT,
                    parent_external_id TEXT,
                    name TEXT NOT NULL,
                    mime_type TEXT,
                    web_url TEXT,
                    selector TEXT,
                    sync_enabled INTEGER DEFAULT 1,
                    ingest_enabled INTEGER DEFAULT 1,
                    last_seen_at TEXT,
                    last_synced_at TEXT,
                    last_ingested_at TEXT,
                    index_status TEXT DEFAULT 'pending',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

            self._ensure_column(connection, "oauth_states", "scopes", "TEXT")
            self._ensure_column(connection, "oauth_states", "code_verifier", "TEXT")
            self._ensure_column(connection, "connected_accounts", "service", "TEXT")
            self._ensure_column(connection, "documents", "storage_bucket", "TEXT")
            self._ensure_column(connection, "documents", "storage_path", "TEXT")
            self._ensure_column(connection, "documents", "error", "TEXT")

            indexes = [
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_default_scope_user
                ON knowledge_scopes(user_id)
                WHERE is_default = 1
                """,
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_scope_resource_identity
                ON scope_resources(
                    scope_id,
                    provider,
                    resource_type,
                    external_id,
                    name
                )
                """,
            ]
            for statement in indexes:
                connection.execute(statement)

    def _ensure_column(
        self,
        connection: sqlite3.Connection,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        columns = [
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        ]
        if column not in columns:
            connection.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
            )

    def save_oauth_state(
        self,
        user_id: str,
        provider: str,
        state: str,
        scopes: list[str] | None = None,
        code_verifier: str | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO oauth_states (
                    state, user_id, provider, scopes, code_verifier, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    state,
                    user_id,
                    provider,
                    json.dumps(scopes or []),
                    code_verifier,
                    utc_now(),
                ),
            )

    def pop_oauth_state(self, state: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT user_id, provider, scopes, code_verifier FROM oauth_states
                WHERE state = ?
                """,
                (state,),
            ).fetchone()

            connection.execute(
                "DELETE FROM oauth_states WHERE state = ?",
                (state,),
            )

        if not row:
            return None

        oauth_state = dict(row)
        oauth_state["scopes"] = json.loads(oauth_state["scopes"] or "[]")
        return oauth_state

    def get_agent_profile(self, user_id: str) -> dict:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM agent_profiles
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()

        if row:
            return dict(row)

        return {
            "user_id": user_id,
            "agent_description": (
                "An agentic co-worker who is professional, concise, "
                "quantitative in reasoning, and action-oriented."
            ),
            "user_context": "",
            "response_preferences": (
                "Prefer clear Markdown, concrete next steps, assumptions, "
                "tradeoffs, and numbers when useful."
            ),
        }

    def upsert_agent_profile(
        self,
        user_id: str,
        agent_description: str = "",
        user_context: str = "",
        response_preferences: str = "",
    ) -> dict:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO agent_profiles (
                    user_id, agent_description, user_context,
                    response_preferences, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    agent_description = excluded.agent_description,
                    user_context = excluded.user_context,
                    response_preferences = excluded.response_preferences,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    agent_description,
                    user_context,
                    response_preferences,
                    now,
                    now,
                ),
            )

        return self.get_agent_profile(user_id)

    def get_or_create_default_scope(self, user_id: str) -> dict:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM knowledge_scopes
                WHERE user_id = ? AND is_default = 1
                """,
                (user_id,),
            ).fetchone()
            if row:
                return dict(row)

            scope_id = str(uuid4())
            now = utc_now()
            connection.execute(
                """
                INSERT INTO knowledge_scopes (
                    id, user_id, name, description, is_default,
                    created_at, updated_at
                )
                VALUES (?, ?, 'Default Knowledge Scope',
                    'Selected resources for workspace retrieval.', 1, ?, ?)
                """,
                (scope_id, user_id, now, now),
            )
            row = connection.execute(
                "SELECT * FROM knowledge_scopes WHERE id = ?",
                (scope_id,),
            ).fetchone()

        return dict(row)

    def list_scope_resources(self, user_id: str, scope_id: str) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM scope_resources
                WHERE user_id = ? AND scope_id = ?
                ORDER BY created_at DESC
                """,
                (user_id, scope_id),
            ).fetchall()

        resources = [dict(row) for row in rows]
        for resource in resources:
            resource["selector"] = json.loads(resource["selector"] or "{}")
            resource["sync_enabled"] = bool(resource["sync_enabled"])
            resource["ingest_enabled"] = bool(resource["ingest_enabled"])
        return resources

    def add_scope_resource(
        self,
        user_id: str,
        scope_id: str,
        provider: str,
        resource_type: str,
        name: str,
        external_id: str | None = None,
        parent_external_id: str | None = None,
        mime_type: str | None = None,
        web_url: str | None = None,
        selector: dict | None = None,
    ) -> dict:
        resource_id = str(uuid4())
        now = utc_now()
        selector = selector or {}

        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO scope_resources (
                    id, scope_id, user_id, provider, resource_type,
                    external_id, parent_external_id, name, mime_type, web_url,
                    selector, sync_enabled, ingest_enabled, last_seen_at,
                    index_status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?, 'pending', ?, ?)
                ON CONFLICT(
                    scope_id, provider, resource_type, external_id, name
                ) DO UPDATE SET
                    parent_external_id = excluded.parent_external_id,
                    mime_type = excluded.mime_type,
                    web_url = excluded.web_url,
                    selector = excluded.selector,
                    sync_enabled = 1,
                    ingest_enabled = 1,
                    last_seen_at = excluded.last_seen_at,
                    updated_at = excluded.updated_at
                """,
                (
                    resource_id,
                    scope_id,
                    user_id,
                    provider,
                    resource_type,
                    external_id,
                    parent_external_id,
                    name,
                    mime_type,
                    web_url,
                    json.dumps(selector),
                    now,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM scope_resources
                WHERE scope_id = ? AND provider = ? AND resource_type = ?
                    AND COALESCE(external_id, '') = COALESCE(?, '')
                    AND name = ?
                """,
                (scope_id, provider, resource_type, external_id, name),
            ).fetchone()

        resource = dict(row)
        resource["selector"] = json.loads(resource["selector"] or "{}")
        resource["sync_enabled"] = bool(resource["sync_enabled"])
        resource["ingest_enabled"] = bool(resource["ingest_enabled"])
        return resource

    def update_scope_resource_status(
        self,
        resource_id: str,
        index_status: str,
        last_synced_at: str | None = None,
        last_ingested_at: str | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE scope_resources
                SET index_status = ?,
                    last_synced_at = COALESCE(?, last_synced_at),
                    last_ingested_at = COALESCE(?, last_ingested_at),
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    index_status,
                    last_synced_at,
                    last_ingested_at,
                    utc_now(),
                    resource_id,
                ),
            )

    def remove_scope_resource(self, user_id: str, resource_id: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                DELETE FROM scope_resources
                WHERE user_id = ? AND id = ?
                """,
                (user_id, resource_id),
            )

    def upsert_connected_account(
        self,
        user_id: str,
        provider: str,
        access_token_encrypted: str,
        refresh_token_encrypted: str | None,
        scopes: list[str],
        expires_at: str | None,
    ) -> str:
        account_id = str(uuid4())
        now = utc_now()

        with self.connect() as connection:
            existing = connection.execute(
                """
                SELECT id FROM connected_accounts
                WHERE user_id = ? AND provider = ?
                """,
                (user_id, provider),
            ).fetchone()
            if existing:
                account_id = existing["id"]

            connection.execute(
                """
                INSERT INTO connected_accounts (
                    id, user_id, provider, access_token_encrypted,
                    service, refresh_token_encrypted, scopes, expires_at,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, provider) DO UPDATE SET
                    service = excluded.service,
                    access_token_encrypted = excluded.access_token_encrypted,
                    refresh_token_encrypted = COALESCE(
                        excluded.refresh_token_encrypted,
                        connected_accounts.refresh_token_encrypted
                    ),
                    scopes = excluded.scopes,
                    expires_at = excluded.expires_at,
                    updated_at = excluded.updated_at
                """,
                (
                    account_id,
                    user_id,
                    provider,
                    access_token_encrypted,
                    provider.removeprefix("google_"),
                    refresh_token_encrypted,
                    json.dumps(scopes),
                    expires_at,
                    now,
                    now,
                ),
            )

        return account_id

    def get_connected_account(self, user_id: str, provider: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM connected_accounts
                WHERE user_id = ? AND provider = ?
                """,
                (user_id, provider),
            ).fetchone()

        if not row:
            return None

        account = dict(row)
        account["scopes"] = json.loads(account["scopes"] or "[]")
        return account

    def list_connected_accounts(self, provider: str | None = None) -> list[dict]:
        query = "SELECT * FROM connected_accounts"
        params: tuple[str, ...] = ()
        if provider:
            query += " WHERE provider = ?"
            params = (provider,)

        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()

        accounts = [dict(row) for row in rows]
        for account in accounts:
            account["scopes"] = json.loads(account["scopes"] or "[]")
        return accounts

    def create_document(
        self,
        user_id: str,
        source: str,
        file_name: str,
        mime_type: str | None = None,
        local_path: str | None = None,
        storage_bucket: str | None = None,
        storage_path: str | None = None,
        external_id: str | None = None,
        web_url: str | None = None,
        checksum: str | None = None,
        modified_at: str | None = None,
        index_status: str = "pending",
        document_id: str | None = None,
    ) -> str:
        document_id = document_id or str(uuid4())
        now = utc_now()

        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO documents (
                    id, user_id, source, external_id, file_name, mime_type,
                    web_url, local_path, storage_bucket, storage_path, checksum,
                    modified_at, index_status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    user_id,
                    source,
                    external_id,
                    file_name,
                    mime_type,
                    web_url,
                    local_path,
                    storage_bucket,
                    storage_path,
                    checksum,
                    modified_at,
                    index_status,
                    now,
                    now,
                ),
            )

        return document_id

    def list_documents(
        self,
        user_id: str,
        limit: int = 100,
        include_deleted: bool = False,
    ) -> list[dict]:
        deleted_filter = "" if include_deleted else "AND index_status != 'deleted'"
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM documents
                WHERE user_id = ?
                {deleted_filter}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()

        return [dict(row) for row in rows]

    def cleanup_chat_indexed_documents(
        self,
        user_id: str,
        keep_document_ids: list[str] | None = None,
    ) -> list[dict]:
        keep_document_ids = keep_document_ids or []
        placeholders = ",".join("?" for _ in keep_document_ids)
        keep_filter = f"AND id NOT IN ({placeholders})" if keep_document_ids else ""

        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM documents
                WHERE user_id = ?
                  AND source != 'upload'
                  AND index_status = 'indexed'
                  {keep_filter}
                """,
                (user_id, *keep_document_ids),
            ).fetchall()

            documents = [dict(row) for row in rows]
            if not documents:
                return []

            now = utc_now()
            document_ids = [document["id"] for document in documents]
            delete_placeholders = ",".join("?" for _ in document_ids)
            connection.execute(
                f"""
                UPDATE documents
                SET index_status = 'deleted', updated_at = ?
                WHERE user_id = ? AND id IN ({delete_placeholders})
                """,
                (now, user_id, *document_ids),
            )
            connection.execute(
                f"""
                UPDATE gmail_messages
                SET deleted_at = ?, updated_at = ?
                WHERE user_id = ? AND document_id IN ({delete_placeholders})
                """,
                (now, now, user_id, *document_ids),
            )

        for document in documents:
            local_path = document.get("local_path")
            if not local_path:
                continue
            try:
                path = Path(local_path)
                if path.is_file():
                    path.unlink()
                    document["local_file_deleted"] = True
            except Exception as exc:
                document["local_file_error"] = str(exc)

        return documents

    def connection_status(self, user_id: str) -> dict:
        accounts = self.list_connected_accounts()
        user_accounts = [
            account for account in accounts
            if account.get("user_id") == user_id
        ]
        providers = {account["provider"] for account in user_accounts}

        return {
            "user_id": user_id,
            "workspace_connected": bool(
                providers.intersection({"google_workspace", "google"})
            ),
            "drive_connected": bool(
                providers.intersection({
                    "google_drive",
                    "google_workspace",
                    "google",
                })
            ),
            "gmail_connected": bool(
                providers.intersection({
                    "google_gmail",
                    "google_workspace",
                    "google",
                })
            ),
            "accounts": [
                {
                    "id": account["id"],
                    "provider": account["provider"],
                    "service": account.get("service"),
                    "scopes": account.get("scopes", []),
                    "expires_at": account.get("expires_at"),
                    "updated_at": account.get("updated_at"),
                }
                for account in user_accounts
            ],
        }

    def upsert_drive_document(
        self,
        user_id: str,
        file: dict,
        local_path: str | None,
        index_status: str = "pending",
    ) -> tuple[str, bool]:
        now = utc_now()
        external_id = file["id"]

        with self.connect() as connection:
            existing = connection.execute(
                """
                SELECT id, checksum, modified_at FROM documents
                WHERE user_id = ? AND source = 'google_drive' AND external_id = ?
                """,
                (user_id, external_id),
            ).fetchone()

            checksum = file.get("md5Checksum")
            modified_at = file.get("modifiedTime")
            is_changed = (
                existing is None
                or existing["checksum"] != checksum
                or existing["modified_at"] != modified_at
            )
            document_id = existing["id"] if existing else str(uuid4())

            connection.execute(
                """
                INSERT INTO documents (
                    id, user_id, source, external_id, file_name, mime_type,
                    web_url, local_path, checksum, modified_at, index_status,
                    created_at, updated_at
                )
                VALUES (?, ?, 'google_drive', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, source, external_id) DO UPDATE SET
                    file_name = excluded.file_name,
                    mime_type = excluded.mime_type,
                    web_url = excluded.web_url,
                    local_path = excluded.local_path,
                    checksum = excluded.checksum,
                    modified_at = excluded.modified_at,
                    index_status = excluded.index_status,
                    updated_at = excluded.updated_at
                """,
                (
                    document_id,
                    user_id,
                    external_id,
                    file.get("name") or external_id,
                    file.get("mimeType"),
                    file.get("webViewLink"),
                    local_path,
                    checksum,
                    modified_at,
                    index_status,
                    now,
                    now,
                ),
            )

        return document_id, is_changed

    def get_document(self, document_id: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM documents WHERE id = ?",
                (document_id,),
            ).fetchone()

        return dict(row) if row else None

    def update_document_status(
        self,
        document_id: str,
        index_status: str,
        indexed_at: str | None = None,
        local_path: str | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE documents
                SET index_status = ?,
                    indexed_at = COALESCE(?, indexed_at),
                    local_path = COALESCE(?, local_path),
                    updated_at = ?
                WHERE id = ?
                """,
                (index_status, indexed_at, local_path, utc_now(), document_id),
            )

    def create_ingestion_job(
        self,
        user_id: str,
        document_id: str,
        reason: str,
    ) -> str:
        job_id = str(uuid4())

        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO ingestion_jobs (
                    id, user_id, document_id, status, reason, created_at
                )
                VALUES (?, ?, ?, 'queued', ?, ?)
                """,
                (job_id, user_id, document_id, reason, utc_now()),
            )

        return job_id

    def update_ingestion_job(
        self,
        job_id: str,
        status: str,
        error: str | None = None,
    ) -> None:
        started_at = utc_now() if status == "running" else None
        finished_at = utc_now() if status in {"indexed", "failed"} else None

        with self.connect() as connection:
            connection.execute(
                """
                UPDATE ingestion_jobs
                SET status = ?,
                    error = COALESCE(?, error),
                    started_at = COALESCE(?, started_at),
                    finished_at = COALESCE(?, finished_at)
                WHERE id = ?
                """,
                (status, error, started_at, finished_at, job_id),
            )

    def get_ingestion_job(self, job_id: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM ingestion_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()

        return dict(row) if row else None

    def get_drive_sync_state(self, user_id: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM drive_sync_state WHERE user_id = ?",
                (user_id,),
            ).fetchone()

        return dict(row) if row else None

    def upsert_drive_sync_state(
        self,
        user_id: str,
        start_page_token: str | None = None,
        channel_id: str | None = None,
        resource_id: str | None = None,
        channel_expiration: str | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO drive_sync_state (
                    user_id, start_page_token, channel_id, resource_id,
                    channel_expiration, last_synced_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    start_page_token = COALESCE(
                        excluded.start_page_token,
                        drive_sync_state.start_page_token
                    ),
                    channel_id = COALESCE(
                        excluded.channel_id,
                        drive_sync_state.channel_id
                    ),
                    resource_id = COALESCE(
                        excluded.resource_id,
                        drive_sync_state.resource_id
                    ),
                    channel_expiration = COALESCE(
                        excluded.channel_expiration,
                        drive_sync_state.channel_expiration
                    ),
                    last_synced_at = excluded.last_synced_at
                """,
                (
                    user_id,
                    start_page_token,
                    channel_id,
                    resource_id,
                    channel_expiration,
                    utc_now(),
                ),
            )

    def upsert_gmail_message(
        self,
        user_id: str,
        message: dict,
        headers: dict,
        body_text: str,
    ) -> tuple[str, bool]:
        now = utc_now()
        gmail_message_id = message["id"]
        gmail_thread_id = message.get("threadId")
        labels = message.get("labelIds", [])
        snippet = message.get("snippet")
        history_id = message.get("historyId")
        internal_date = message.get("internalDate")
        subject = headers.get("subject") or "(no subject)"
        sender = headers.get("from")
        recipient = headers.get("to")
        checksum = f"{history_id}:{len(body_text)}:{','.join(labels)}"

        with self.connect() as connection:
            existing = connection.execute(
                """
                SELECT document_id, history_id, labels FROM gmail_messages
                WHERE user_id = ? AND gmail_message_id = ?
                """,
                (user_id, gmail_message_id),
            ).fetchone()

            document_id = existing["document_id"] if existing else str(uuid4())
            is_changed = (
                existing is None
                or existing["history_id"] != history_id
                or existing["labels"] != json.dumps(labels)
            )

            connection.execute(
                """
                INSERT INTO documents (
                    id, user_id, source, external_id, file_name, mime_type,
                    checksum, modified_at, index_status, created_at, updated_at
                )
                VALUES (?, ?, 'gmail', ?, ?, 'message/rfc822', ?, ?, 'queued', ?, ?)
                ON CONFLICT(user_id, source, external_id) DO UPDATE SET
                    file_name = excluded.file_name,
                    checksum = excluded.checksum,
                    modified_at = excluded.modified_at,
                    index_status = excluded.index_status,
                    updated_at = excluded.updated_at
                """,
                (
                    document_id,
                    user_id,
                    gmail_message_id,
                    subject,
                    checksum,
                    history_id,
                    now,
                    now,
                ),
            )

            connection.execute(
                """
                INSERT INTO gmail_messages (
                    id, document_id, user_id, gmail_message_id,
                    gmail_thread_id, subject, sender, recipient, snippet,
                    internal_date, history_id, labels, deleted_at,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                ON CONFLICT(user_id, gmail_message_id) DO UPDATE SET
                    gmail_thread_id = excluded.gmail_thread_id,
                    subject = excluded.subject,
                    sender = excluded.sender,
                    recipient = excluded.recipient,
                    snippet = excluded.snippet,
                    internal_date = excluded.internal_date,
                    history_id = excluded.history_id,
                    labels = excluded.labels,
                    deleted_at = NULL,
                    updated_at = excluded.updated_at
                """,
                (
                    str(uuid4()) if existing is None else document_id,
                    document_id,
                    user_id,
                    gmail_message_id,
                    gmail_thread_id,
                    subject,
                    sender,
                    recipient,
                    snippet,
                    internal_date,
                    history_id,
                    json.dumps(labels),
                    now,
                    now,
                ),
            )

        return document_id, is_changed

    def mark_gmail_message_indexed(
        self,
        user_id: str,
        gmail_message_id: str,
    ) -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE gmail_messages
                SET indexed_at = ?, updated_at = ?
                WHERE user_id = ? AND gmail_message_id = ?
                """,
                (now, now, user_id, gmail_message_id),
            )

    def get_gmail_message(
        self,
        user_id: str,
        gmail_message_id: str,
    ) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM gmail_messages
                WHERE user_id = ? AND gmail_message_id = ?
                """,
                (user_id, gmail_message_id),
            ).fetchone()

        if not row:
            return None

        message = dict(row)
        message["labels"] = json.loads(message["labels"] or "[]")
        return message

    def list_gmail_messages(
        self,
        user_id: str,
        limit: int = 50,
    ) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM gmail_messages
                WHERE user_id = ? AND deleted_at IS NULL
                ORDER BY internal_date DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()

        messages = [dict(row) for row in rows]
        for message in messages:
            message["labels"] = json.loads(message["labels"] or "[]")
        return messages

    def mark_gmail_message_deleted(
        self,
        user_id: str,
        gmail_message_id: str,
    ) -> str | None:
        now = utc_now()
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT document_id FROM gmail_messages
                WHERE user_id = ? AND gmail_message_id = ?
                """,
                (user_id, gmail_message_id),
            ).fetchone()

            if not row:
                return None

            connection.execute(
                """
                UPDATE gmail_messages
                SET deleted_at = ?, updated_at = ?
                WHERE user_id = ? AND gmail_message_id = ?
                """,
                (now, now, user_id, gmail_message_id),
            )
            connection.execute(
                """
                UPDATE documents
                SET index_status = 'deleted', updated_at = ?
                WHERE id = ?
                """,
                (now, row["document_id"]),
            )

        return row["document_id"]

    def get_gmail_sync_state(self, user_id: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM gmail_sync_state WHERE user_id = ?",
                (user_id,),
            ).fetchone()

        return dict(row) if row else None

    def upsert_gmail_sync_state(
        self,
        user_id: str,
        email_address: str | None = None,
        last_history_id: str | None = None,
        full_sync: bool = False,
        partial_sync: bool = False,
        watch_expiration: str | None = None,
        pubsub_topic: str | None = None,
    ) -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO gmail_sync_state (
                    user_id, email_address, last_history_id,
                    last_full_sync_at, last_partial_sync_at, watch_expiration,
                    pubsub_topic, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    email_address = COALESCE(
                        excluded.email_address,
                        gmail_sync_state.email_address
                    ),
                    last_history_id = COALESCE(
                        excluded.last_history_id,
                        gmail_sync_state.last_history_id
                    ),
                    last_full_sync_at = COALESCE(
                        excluded.last_full_sync_at,
                        gmail_sync_state.last_full_sync_at
                    ),
                    last_partial_sync_at = COALESCE(
                        excluded.last_partial_sync_at,
                        gmail_sync_state.last_partial_sync_at
                    ),
                    watch_expiration = COALESCE(
                        excluded.watch_expiration,
                        gmail_sync_state.watch_expiration
                    ),
                    pubsub_topic = COALESCE(
                        excluded.pubsub_topic,
                        gmail_sync_state.pubsub_topic
                    ),
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    email_address,
                    last_history_id,
                    now if full_sync else None,
                    now if partial_sync else None,
                    watch_expiration,
                    pubsub_topic,
                    now,
                    now,
                ),
            )
