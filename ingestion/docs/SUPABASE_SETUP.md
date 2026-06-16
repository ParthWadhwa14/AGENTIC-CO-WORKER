# Supabase Setup

Use Supabase for:

- Auth
- PostgreSQL metadata
- private upload storage

Keep Qdrant for vector search.

## 1. Create Supabase Project

Create a Supabase project, then copy:

- Project URL
- anon public key
- service role key
- Postgres connection string

Use the service role key only in the FastAPI backend.

## 2. Enable Auth

In Supabase:

```text
Authentication -> Providers -> Google -> Enable
```

Use this for app login. Add a Google OAuth Client ID and Client Secret in this
Supabase provider screen. If this is not enabled, the frontend will show:

```text
Unsupported provider: provider is not enabled
```

The backend Google OAuth connection buttons are separate and are still used for
Drive/Docs/Sheets and Gmail data scopes after the user has logged in.

You can also enable the Email provider and use magic-link login while setting up
Google login.

## 3. Create Storage Bucket

Create a private bucket:

```text
user-uploads
```

Uploads are stored at:

```text
{user_id}/uploads/{document_id}/{file_name}
```

## 4. Create Tables

Run `ingestion/db/schema.sql` in the Supabase SQL editor.

## 5. Backend Env

Set in backend `.env`:

```bash
SUPABASE_URL=https://YOUR_PROJECT_ID.supabase.co
SUPABASE_ANON_KEY=your_anon_key
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
SUPABASE_UPLOAD_BUCKET=user-uploads
DATABASE_URL=postgresql+psycopg2://...
METADATA_DATABASE_URL=sqlite:///ingestion/app.db
```

Local development can still use:

```bash
DATABASE_URL=sqlite:///ingestion/app.db
METADATA_DATABASE_URL=sqlite:///ingestion/app.db
```

`DATABASE_URL` is the Supabase/Postgres connection used by SQLAlchemy and
`create_tables.py`. `METADATA_DATABASE_URL` keeps the current local MVP
metadata store running until the operational endpoints are fully migrated to
SQLAlchemy migrations.

## 6. Frontend Env

Set in `frontend/.env.local`:

```bash
NEXT_PUBLIC_SUPABASE_URL=https://YOUR_PROJECT_ID.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your_anon_key
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
```

## 7. Run

Backend:

```bash
cd ingestion
uvicorn app.server:app --reload --port 8000
```

Frontend:

```bash
cd frontend
npm i
npm run dev
```

Open:

```text
http://localhost:3000
```
