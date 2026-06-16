# Google Drive, Docs, Sheets, and Gmail Setup

This backend uses direct Google APIs. MCP can be added later as a wrapper, but OAuth, sync, and permissions live here.

## 1. Google Cloud

Create a Google Cloud project and enable:

- Google Drive API
- Google Docs API
- Google Sheets API
- Gmail API

Configure the OAuth consent screen as `External` for normal Google/Gmail accounts. In testing mode, add your own Google account as a test user.

## 2. OAuth Client

Create an OAuth client:

- Application type: `Web application`
- Local redirect URI: `http://localhost:8000/auth/google/callback`

Download the client JSON and set:

```bash
GOOGLE_CLIENT_SECRETS_FILE=/absolute/path/to/client_secret.json
GOOGLE_OAUTH_REDIRECT_URI=http://localhost:8000/auth/google/callback
FRONTEND_URL=http://localhost:3000
```

Or set the client ID and secret directly:

```bash
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_OAUTH_REDIRECT_URI=http://localhost:8000/auth/google/callback
FRONTEND_URL=http://localhost:3000
```

## 3. Env

Copy `ingestion/.env.example` to `.env`, then set:

```bash
TOKEN_ENCRYPTION_KEY=...
GROQ_API_KEY=...
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
```

Generate the token key:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## 4. Run

Start Qdrant:

```bash
cd ingestion
docker compose up -d
```

Start the API:

```bash
cd ingestion
uvicorn app.server:app --reload --port 8000
```

Open API docs:

```text
http://localhost:8000/docs
```

## 4.1. Agent Model

The LangGraph agent uses `GROQ_API_KEY` through `langchain-groq`.

Default models:

```bash
GENERATION_MODEL=openai/gpt-oss-120b
FALLBACK_GENERATION_MODEL=openai/gpt-oss-20b
```

Streaming is available at:

```text
POST /agent/stream
```

Non-streaming formatted answers are available at:

```text
POST /agent/ask
```

## 5. Connect Accounts

Connect everything at once:

```text
GET /auth/google/start?user_id=local-user&service=workspace
```

Privacy-first separate buttons:

```text
GET /auth/google/start?user_id=local-user&service=drive
GET /auth/google/start?user_id=local-user&service=gmail
```

Drive requests read-only Drive, Docs, and Sheets scopes.
Gmail requests only `gmail.readonly` by default.

## 6. Upload And Sync

Upload local files:

```text
POST /upload
```

List supported Drive files:

```text
GET /drive/files?user_id=local-user
```

Sync Drive:

```text
POST /drive/sync?user_id=local-user&mode=initial
POST /drive/sync?user_id=local-user&mode=incremental
```

Sync Gmail:

```text
POST /gmail/sync?user_id=local-user&mode=initial&max_messages=100
POST /gmail/sync?user_id=local-user&mode=partial
```

Default Gmail ingestion query:

```text
newer_than:180d -in:spam -in:trash
```

Use stricter filters for privacy, for example:

```text
newer_than:90d -in:spam -in:trash label:important
```

Search indexed chunks:

```text
GET /search?query=interview&source_type=gmail
GET /search?query=jee rank&source_type=pdf
```

Ask the LangGraph agent:

```text
POST /agent/ask
{
  "user_id": "local-user",
  "query": "What does my resume say about achievements?",
  "source_type": "pdf",
  "limit": 8
}
```

Stream the formatted answer as Server-Sent Events:

```text
POST /agent/stream
```

Agent answers include a `references` array. Each reference has an `open_url`
that can be used by the frontend as a one-click source link. Local uploads open
through `/references/{document_id}/open`; Gmail opens in Gmail; Drive files use
their Google web URL when available.

Trigger all connected account syncs during development:

```text
POST /sync/all
```

For a simple scheduled job, run this every 15-30 minutes:

```bash
cd ingestion
PYTHONPATH=. python -c "from app.sync.periodic_sync import sync_all_connected_accounts; print(sync_all_connected_accounts())"
```

## 7. Production Notes

- Keep Gmail read-only until approval flows are built for drafts/sending.
- Do not index all Gmail by default. Prefer time ranges, labels, and explicit user choices.
- Use `gmail.history.list` partial sync every 15-30 minutes for MVP.
- Add Gmail Pub/Sub push notifications later for near-real-time sync.
- Replace the local SQLite `MetadataStore` with PostgreSQL using `db/schema.sql` when deploying.
