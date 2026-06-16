CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS users_profile (
    id UUID PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    name TEXT,
    avatar_url TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS connected_accounts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL,
    provider TEXT NOT NULL,
    service TEXT NOT NULL,
    access_token_encrypted TEXT,
    refresh_token_encrypted TEXT,
    scopes TEXT[],
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, provider)
);

CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL,
    source TEXT NOT NULL,
    external_id TEXT,
    file_name TEXT NOT NULL,
    mime_type TEXT,
    web_url TEXT,
    local_path TEXT,
    storage_bucket TEXT,
    storage_path TEXT,
    checksum TEXT,
    modified_at TIMESTAMPTZ,
    indexed_at TIMESTAMPTZ,
    index_status TEXT DEFAULT 'pending',
    error TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, source, external_id)
);

CREATE TABLE IF NOT EXISTS ingestion_jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL,
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    status TEXT DEFAULT 'queued',
    reason TEXT,
    error TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS drive_sync_state (
    user_id UUID PRIMARY KEY,
    start_page_token TEXT,
    channel_id TEXT,
    resource_id TEXT,
    channel_expiration TIMESTAMPTZ,
    last_synced_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS gmail_messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    user_id UUID NOT NULL,
    gmail_message_id TEXT NOT NULL,
    gmail_thread_id TEXT,
    subject TEXT,
    sender TEXT,
    recipient TEXT,
    snippet TEXT,
    internal_date TIMESTAMPTZ,
    history_id TEXT,
    labels TEXT[],
    indexed_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, gmail_message_id)
);

CREATE TABLE IF NOT EXISTS gmail_sync_state (
    user_id UUID PRIMARY KEY,
    email_address TEXT,
    last_history_id TEXT,
    last_full_sync_at TIMESTAMPTZ,
    last_partial_sync_at TIMESTAMPTZ,
    watch_expiration TIMESTAMPTZ,
    pubsub_topic TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL,
    thread_id TEXT,
    query TEXT NOT NULL,
    intent TEXT,
    status TEXT DEFAULT 'running',
    final_answer TEXT,
    trace JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS proposed_actions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL,
    agent_run_id UUID REFERENCES agent_runs(id) ON DELETE CASCADE,
    action_type TEXT NOT NULL,
    payload JSONB NOT NULL,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    approved_at TIMESTAMPTZ,
    rejected_at TIMESTAMPTZ,
    executed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL,
    event_type TEXT NOT NULL,
    source TEXT,
    payload JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oauth_states (
    state TEXT PRIMARY KEY,
    user_id UUID NOT NULL,
    provider TEXT NOT NULL,
    scopes TEXT[],
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
