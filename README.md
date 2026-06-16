# Agentic Workspace Co-Worker

An agentic workspace assistant with a Next.js frontend and FastAPI backend. It connects to Supabase Auth, Google Drive, Google Docs, Google Sheets, Gmail, Qdrant vector search, Groq-hosted LLMs, and Serper web search so a user can chat with their own workspace, prioritize documents, retrieve live Google Workspace resources, and approve guarded write actions.

The project is built as a practical personal co-worker rather than a plain chatbot. It can ingest selected files, search indexed workspace context, discover live Google resources through OAuth, remember durable user context, draft or send Gmail messages, create or update Google Docs, and update Google Sheets only after explicit approval.

## What This Project Does

- Authenticates users with Supabase.
- Connects a user's Google Workspace account through backend OAuth.
- Ingests uploaded files and selected Google Workspace resources.
- Parses and chunks PDFs, TXT files, Google Docs, PPTX files, and other document formats with structural metadata.
- Registers CSV, XLSX, and Google Sheets as table sources instead of blindly vector-indexing large tabular data.
- Stores document metadata, OAuth state, connected accounts, ingestion jobs, agent profiles, Gmail metadata, and selected resources in a local SQLite metadata store.
- Stores semantic chunks in Qdrant using FastEmbed embeddings.
- Runs a LangGraph agent that routes, plans, retrieves, evaluates relevance, answers, and proposes guarded actions.
- Uses Groq for generation, with `openai/gpt-oss-120b` as the default model and `openai/gpt-oss-20b` as fallback.
- Uses Serper web search only when the query needs current or external information.
- Supports two chat modes:
  - Workspace RAG: searches indexed and live workspace sources.
  - Basic chat: general assistant mode with optional web search.
- Supports explicit write actions:
  - Gmail draft creation.
  - Gmail sending.
  - Google Docs create/update.
  - Google Sheets create/update.
- Requires user approval for every write action.
- Shows clickable references and retrieved sources in the UI.
- Lets users prioritize indexed documents for the current chat or keep them prioritized across chats.
- Cleans temporary indexed Google resources on clear chat while preserving uploaded files and keep-marked resources.

## Tech Stack

### Frontend

- Next.js 15
- React 19
- TypeScript
- Tailwind CSS
- Supabase JS client
- Lucide React icons

### Backend

- FastAPI
- LangGraph
- LangChain core/community
- Groq through `langchain-groq`
- Qdrant vector database
- FastEmbed embeddings
- SQLite metadata store for the local MVP
- Google API Python Client
- Google OAuth
- Supabase Python client
- PyMuPDF and document loaders
- Pandas/OpenPyXL for table-oriented paths

### External Services

- Supabase Auth
- Google Drive API
- Google Docs API
- Google Sheets API
- Gmail API
- Qdrant
- Groq
- Serper

## Repository Structure

```text
.
+-- frontend/                  # Next.js app
|   +-- app/                   # App router pages and global CSS
|   +-- components/            # Login and workspace UI
|   +-- lib/                   # API and Supabase clients
+-- ingestion/                 # FastAPI backend package and local data
|   +-- app/
|   |   +-- agent/             # LangGraph agent state, graph, nodes, prompts, service
|   |   +-- api/               # FastAPI routers
|   |   +-- connectors/        # Google Drive, Docs, Sheets, Gmail connectors
|   |   +-- loaders/           # PDF, TXT, Docs, Gmail, PPTX, CSV/XLSX loaders
|   |   +-- services/          # OAuth, runtime, web search, action executor, jobs
|   |   +-- storage/           # SQLite metadata store and Supabase storage helper
|   |   +-- sync/              # Drive/Gmail sync services
|   |   +-- tools/             # Retrieval tool wrapper
|   |   +-- chunking.py        # Structure-aware chunk builders
|   |   +-- qdrant_store.py    # Qdrant vector operations
|   |   +-- server.py          # FastAPI app entrypoint
|   +-- docs/                  # Supabase and Google setup guides
|   +-- docker-compose.yml     # Qdrant and Redis services
+-- requirements.txt           # Python dependencies
+-- README.md
```

## Architecture Overview

The application is split into four main layers:

```text
Next.js UI
  |
  | Supabase session user id + chat/action requests
  v
FastAPI backend
  |
  | agent orchestration, OAuth, ingestion, retrieval, write actions
  v
Storage and tools
  |
  | SQLite metadata, Qdrant vectors, local uploaded files,
  | Google APIs, Groq, Serper
  v
User workspace answers and approved actions
```

### 1. Frontend Layer

The frontend is the user's workspace console. It handles:

- Supabase login and auth callback.
- Google source connection cards.
- File upload.
- Selected resource ingestion from Drive, Docs, Sheets, and Gmail.
- Workspace chat and basic chat modes.
- Markdown answer rendering.
- Retrieved source sidebar.
- Indexed document priority checkboxes.
- Keep-priority behavior across chats.
- Action approval cards with risk level, preview, guardrail warning, and payload preview.

The frontend sends the Supabase user id to the backend. The backend uses that user id to isolate metadata, connected Google accounts, indexed documents, and agent profile state.

### 2. Backend API Layer

The backend is a FastAPI app in `ingestion/app/server.py`. It mounts routers for:

- `/agent`: chat, streaming, profile, action execution.
- `/auth`: Google OAuth callback and connection flows.
- `/drive`, `/gmail`, `/sync`, `/sources`: Google discovery, selected ingestion, and sync.
- `/upload`: user file upload and indexing jobs.
- `/search`: workspace search.
- `/references`: opening local references.
- `/status`: setup, connection, and indexed document status.

The API layer is intentionally thin. Most behavior lives in services, connectors, and the LangGraph agent nodes.

### 3. Agent Layer

The agent is implemented with LangGraph. The graph is:

```text
START
  |
  v
route_intent
  |
  v
plan
  |
  v
retrieve
  |
  +--> answer --------+
  |                   |
  +--> prepare_action |
          |           |
          v           |
        answer        |
          |           |
          v           |
        format <------+
          |
          v
END
```

The main state object includes:

- User id.
- Current query.
- Conversation history.
- Runtime context.
- Agent profile.
- Web results.
- Pinned and priority document ids.
- Retrieval attempt count.
- Intent and plan.
- Retrieved chunks.
- Proposed action.
- Final answer and references.
- Errors and trace.

The agent does more than simple RAG:

- It routes intent into document search, Gmail search, table analysis, Docs action, Sheets action, Gmail draft/send, or general chat.
- It plans the next steps.
- It searches authenticated Google Workspace sources first when the user asks about workspace materials.
- It can do one bounded retrieval expansion if context is weak.
- It evaluates retrieved and web context for relevance before answer/action generation.
- It proposes write actions but never executes them without explicit approval.
- It resolves easy missing fields itself, such as spreadsheet ids, document ids, previous draft ids, document URLs, and uploaded resume attachment paths.

### 4. Retrieval And Ingestion Layer

The retrieval architecture separates document metadata from semantic chunks.

```text
Upload / selected Google resource / Gmail message
  |
  v
MetadataStore record in SQLite
  |
  v
Loader parses source into structured ParsedElement objects
  |
  v
Chunking builds Chunk objects with document, page, heading, row, sheet, slide metadata
  |
  v
FastEmbed creates vectors
  |
  v
Qdrant stores vectors and payload metadata
  |
  v
Agent retrieves relevant chunks and builds clickable references
```

The chunking system keeps structure in the embedding text. For example, chunks include:

- Document name.
- Source type.
- Chunk type.
- Page number.
- Sheet name.
- Slide number.
- Row ranges.
- Heading path.
- Section metadata.

This makes retrieval more useful than raw text splitting because the model sees where a passage came from and the UI can produce meaningful references.

### 5. Google Workspace Architecture

Google Workspace access is handled by a backend OAuth flow. Tokens are stored through the metadata/token service and are used by backend connectors.

The project supports:

- Drive file discovery and download/export.
- Google Docs export/read and create/update.
- Google Sheets discovery/read/update/create.
- Gmail metadata/full-message retrieval, draft creation, sending, and draft sending.

The agent uses Google Workspace as the first-class source of truth for personal/workspace tasks. Indexed documents are useful, but the agent can also perform live Google discovery when it needs file metadata, URLs, ids, or Gmail context.

### 6. Selected Ingestion

The app avoids a dangerous "sync everything" workflow. Instead, it supports selected ingestion:

1. The user selects Drive, Docs, Sheets, or Gmail.
2. The user can provide a focus instruction.
3. The agent creates safe metadata searches.
4. The UI shows candidate resources.
5. Only selected resources are registered or ingested.

This keeps the workspace private, controlled, and memory-efficient.

### 7. Table Source Handling

CSV, XLSX, and Google Sheets are treated conservatively.

Large tables are not blindly chunked into vector memory. Instead, they are registered as `table_source`, so future table analysis can use a structured path rather than unreliable semantic retrieval over rows.

This is important because vector search is usually poor for exact row counts, filters, joins, and numeric analysis.

### 8. Action Guardrail Architecture

Write actions are split into two phases:

```text
User asks for a write action
  |
  v
Agent proposes action payload
  |
  v
Backend validates guardrails
  |
  v
Frontend shows risk, preview, warning, payload
  |
  v
User explicitly approves
  |
  v
Backend executes Google API call
  |
  v
Backend verifies API result
```

Guardrails include:

- No execution without explicit approval.
- Allowed action types only.
- Recipient validation.
- Attachment validation by local file path and size.
- Max attachment count.
- Sheet cell count limits.
- Required Google ids and ranges.
- Verification that Google APIs return expected ids/update counts.
- Blocking of unsafe or malformed action payloads.

The agent is expected to fix small missing-field issues itself when the information is available from chat history, retrieved context, live Google discovery, or local metadata.

### 9. Memory Model

The application uses several memory scopes:

- Chat transcript memory in the frontend.
- Durable user context in the agent profile.
- Indexed uploaded documents.
- Temporarily indexed selected Google resources.
- Keep-priority documents that persist across chats.
- Per-answer retrieved sources.
- Hidden action execution memory so follow-up requests can refer to previous drafts, docs, sheets, or action results.

When a user clears chat, temporary indexed Google resources can be cleaned up to save memory. Uploaded frontend documents remain saved, and keep-marked resources are preserved.

## Prerequisites

- Python 3.11 or newer recommended.
- Node.js 20 or newer recommended.
- Docker Desktop or another Docker runtime.
- A Supabase project.
- A Google Cloud project with OAuth consent and APIs enabled.
- A Groq API key.
- Optional: a Serper API key for web search.

## Setup Guide

### 1. Clone And Enter The Project

```bash
git clone <your-repo-url>
cd "AGENTIC CO_WORKER"
```

If you already have the project locally, start from the project root.

### 2. Start Qdrant

```bash
cd ingestion
docker compose up -d qdrant
cd ..
```

Redis is also listed in `ingestion/docker-compose.yml`, but the current core flow mainly depends on Qdrant and the metadata database.

### 3. Configure Backend Environment

Create `ingestion/.env` from the example:

```bash
cp ingestion/.env.example ingestion/.env
```

Fill the important values:

```bash
QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=
QDRANT_COLLECTION=personal_workspace_chunks
EMBEDDING_MODEL=BAAI/bge-small-en-v1.5

GROQ_API_KEY=your_groq_key
GENERATION_MODEL=openai/gpt-oss-120b
FALLBACK_GENERATION_MODEL=openai/gpt-oss-20b
GROQ_CONTEXT_CHAR_LIMIT=70000
GROQ_MAX_OUTPUT_TOKENS=4096

DATABASE_URL=sqlite:///ingestion/app.db
METADATA_DATABASE_URL=sqlite:///ingestion/app.db

SUPABASE_URL=https://YOUR_PROJECT_ID.supabase.co
SUPABASE_ANON_KEY=your_supabase_anon_key
SUPABASE_SERVICE_ROLE_KEY=your_supabase_service_role_key
SUPABASE_UPLOAD_BUCKET=user-uploads

UPLOAD_DIR=ingestion/uploaded_files
DRIVE_DOWNLOAD_DIR=ingestion/synced_drive_files

TOKEN_ENCRYPTION_KEY=your_fernet_key

GOOGLE_CLIENT_ID=your_google_client_id
GOOGLE_CLIENT_SECRET=your_google_client_secret
GOOGLE_OAUTH_REDIRECT_URI=http://localhost:8000/auth/google/callback
FRONTEND_URL=http://localhost:3000
# Railway production:
# FRONTEND_URL=https://agentic-co-worker.vercel.app

SERPER_API_KEY=your_serper_key_optional
```

Generate `TOKEN_ENCRYPTION_KEY` with:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

For local Google OAuth over HTTP, you may need:

```bash
OAUTHLIB_INSECURE_TRANSPORT=1
```

### 4. Configure Google Cloud

In Google Cloud Console:

1. Create or select a project.
2. Configure the OAuth consent screen.
3. Create an OAuth client for a web application.
4. Add this redirect URI:

```text
http://localhost:8000/auth/google/callback
```

5. Enable these APIs:
   - Google Drive API
   - Google Docs API
   - Google Sheets API
   - Gmail API

The backend scopes include read access for Drive, Docs, Sheets, Gmail, plus write scopes for Gmail compose/send, Docs, and Sheets. If scopes change, reconnect Google in the app so the token has the new permissions.

More details are in `ingestion/docs/GOOGLE_SETUP.md`.

### 5. Configure Supabase

In Supabase:

1. Create a project.
2. Enable at least one Auth provider.
3. For Google login through Supabase, enable Google under Authentication providers.
4. Add the frontend callback URL:

```text
http://localhost:3000/auth/callback
```

5. If using Supabase Storage for uploads, create/configure the upload bucket named by `SUPABASE_UPLOAD_BUCKET`.

More details are in `ingestion/docs/SUPABASE_SETUP.md`.

### 6. Install Backend Dependencies

From the project root:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 7. Run The Backend

```bash
PYTHONPATH=ingestion python3 -m uvicorn app.server:app --host 127.0.0.1 --port 8000 --reload
```

Health check:

```text
http://localhost:8000/health
```

### 8. Configure Frontend Environment

Create `frontend/.env.local`:

```bash
cp frontend/.env.example frontend/.env.local
```

Fill:

```bash
NEXT_PUBLIC_SUPABASE_URL=https://YOUR_PROJECT_ID.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your_supabase_anon_or_publishable_key
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
```

For Vercel, set `NEXT_PUBLIC_BACKEND_URL` to the Railway backend URL:
`https://agentic-co-worker-production.up.railway.app`. Do not set it to the
Vercel frontend URL.

### 9. Install And Run The Frontend

```bash
cd frontend
npm i
npm run dev
```

Open:

```text
http://localhost:3000
```

## Day-To-Day Workflow

1. Start Qdrant.
2. Start the FastAPI backend.
3. Start the Next.js frontend.
4. Sign in with Supabase.
5. Connect Google Workspace from the UI.
6. Upload documents or use Agent Pick + Ingest.
7. Ask workspace questions.
8. Prioritize documents with the checkbox if a chat should focus on them.
9. Use the keep checkbox if a document should stay prioritized across chats.
10. Review and approve write actions only after checking the preview.

## Environment Variables

### Backend

| Variable | Purpose |
| --- | --- |
| `QDRANT_URL` | Qdrant server URL. |
| `QDRANT_API_KEY` | Qdrant API key. Leave empty for local Docker Qdrant; set it for Qdrant Cloud. |
| `QDRANT_COLLECTION` | Collection used for workspace chunks. |
| `EMBEDDING_MODEL` | FastEmbed embedding model. |
| `GROQ_API_KEY` | Groq API key for LLM generation. |
| `GENERATION_MODEL` | Primary generation model. |
| `FALLBACK_GENERATION_MODEL` | Backup generation model. |
| `GROQ_CONTEXT_CHAR_LIMIT` | Prompt compaction limit for Groq context. |
| `GROQ_MAX_OUTPUT_TOKENS` | Max generation output tokens. |
| `DATABASE_URL` | Local database URL. |
| `METADATA_DATABASE_URL` | Metadata store database URL. |
| `SUPABASE_URL` | Supabase project URL. |
| `SUPABASE_ANON_KEY` | Supabase anon/publishable key. |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase server-side service key. |
| `SUPABASE_UPLOAD_BUCKET` | Bucket for uploaded files. |
| `UPLOAD_DIR` | Local directory for uploaded files. |
| `DRIVE_DOWNLOAD_DIR` | Local directory for exported/downloaded Drive files. |
| `TOKEN_ENCRYPTION_KEY` | Fernet key for token encryption. |
| `GOOGLE_CLIENT_ID` | Google OAuth client id. |
| `GOOGLE_CLIENT_SECRET` | Google OAuth client secret. |
| `GOOGLE_OAUTH_REDIRECT_URI` | Backend OAuth callback URL. |
| `FRONTEND_URL` | Frontend URL used after OAuth. |
| `SERPER_API_KEY` | Optional web search API key. |

### Frontend

| Variable | Purpose |
| --- | --- |
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase project URL. |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase browser key. |
| `NEXT_PUBLIC_BACKEND_URL` | FastAPI backend URL. In production this should be the Railway backend URL, not the Vercel frontend URL. |

## Important API Endpoints

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Backend health check. |
| `POST /agent/ask` | Main agent request. |
| `POST /agent/stream` | Streaming agent response. |
| `GET /agent/profile` | Get agent profile. |
| `PUT /agent/profile` | Update agent profile. |
| `POST /agent/actions/execute` | Execute approved action. |
| `POST /upload` | Upload a local file. |
| `GET /setup/status` | Setup/config readiness. |
| `GET /documents` | Indexed document status. |
| `POST /documents/cleanup-chat` | Clear temporary chat-indexed resources. |
| `GET /references/{document_id}/open` | Open a local/clickable reference. |

## Verification Commands

Backend compile:

```bash
python3 -m compileall ingestion/app
```

Backend import:

```bash
PYTHONPATH=ingestion python3 -c "from app.server import app; print('app import ok')"
```

Frontend typecheck:

```bash
cd frontend
npm run typecheck
```

Frontend production build:

```bash
cd frontend
npm run build
```

## Design Principles

- Google Workspace is a first-class source, not a secondary fallback.
- The agent should resolve easy missing information by itself when available.
- Web search should be used only when relevant, not as noise.
- Retrieval results are candidate evidence, not automatically trusted evidence.
- Write actions require approval every time.
- Uploads are durable; temporary indexed workspace resources can be cleaned up.
- Tables should use structured analysis paths instead of naive vector RAG.
- User memory should store durable working context, not secrets or one-off commands.
- The UI should make actions inspectable before execution.

## Current Limitations

- The metadata store is SQLite for the local MVP. PostgreSQL migration is implied by the schema but not fully wired as the default runtime store.
- Rich analytics over large CSV/XLSX/Google Sheets needs further improvement.
- Gmail attachments require a real local uploaded file path. Drive-only files must be downloaded/ingested or attached as links unless converted into local upload metadata.
- Existing approval cards generated before a code change may contain stale payloads; regenerate the action after restarting the backend.
- Google OAuth tokens must be refreshed/reconnected after scope changes.

## Common Troubleshooting

### Qdrant Search Fails

- Make sure Qdrant is running:

```bash
cd ingestion
docker compose up -d qdrant
```

- Check `QDRANT_URL`.
- Confirm the document status is `indexed`.

### Google OAuth Works But Actions Fail

- Reconnect Google after scope changes.
- Confirm the required API is enabled in Google Cloud.
- Confirm the token has Gmail send/compose or Docs/Sheets write scopes.

### LLM Generation Fails

- Confirm `GROQ_API_KEY` is set in `ingestion/.env`.
- Confirm `GENERATION_MODEL=openai/gpt-oss-120b`.
- Restart the backend after changing `.env`.

### Supabase Login Fails

- Confirm frontend env variables.
- Confirm Supabase Auth callback URL:

```text
http://localhost:3000/auth/callback
```

- Confirm the selected provider is enabled in Supabase.

## Security Notes

- Do not commit `.env`, local databases, uploaded files, synced Drive files, caches, `.next`, `node_modules`, or virtual environments.
- OAuth tokens should remain encrypted with `TOKEN_ENCRYPTION_KEY`.
- Keep Supabase service role keys server-side only.
- Treat write actions as high-risk until the user approves the preview.

## License

No license has been specified yet.
