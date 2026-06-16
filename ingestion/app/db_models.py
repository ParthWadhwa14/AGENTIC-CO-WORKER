import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.sql import func

from app.db import Base


class UserProfile(Base):
    __tablename__ = "users_profile"

    id = Column(UUID(as_uuid=True), primary_key=True)
    email = Column(Text, unique=True, nullable=False)
    name = Column(Text)
    avatar_url = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now())


class ConnectedAccount(Base):
    __tablename__ = "connected_accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    provider = Column(Text, nullable=False)
    service = Column(Text, nullable=False)
    access_token_encrypted = Column(Text)
    refresh_token_encrypted = Column(Text)
    scopes = Column(ARRAY(Text))
    expires_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now())


class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    source = Column(Text, nullable=False)
    external_id = Column(Text)
    file_name = Column(Text, nullable=False)
    mime_type = Column(Text)
    web_url = Column(Text)
    local_path = Column(Text)
    storage_bucket = Column(Text)
    storage_path = Column(Text)
    checksum = Column(Text)
    modified_at = Column(DateTime)
    indexed_at = Column(DateTime)
    index_status = Column(Text, default="pending")
    error = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now())


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
    )
    status = Column(Text, default="queued")
    reason = Column(Text)
    error = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
    started_at = Column(DateTime)
    finished_at = Column(DateTime)


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    thread_id = Column(Text)
    query = Column(Text, nullable=False)
    intent = Column(Text)
    status = Column(Text, default="running")
    final_answer = Column(Text)
    trace = Column(JSONB)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now())


class ProposedAction(Base):
    __tablename__ = "proposed_actions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    agent_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
    )
    action_type = Column(Text, nullable=False)
    payload = Column(JSONB, nullable=False)
    status = Column(Text, default="pending")
    created_at = Column(DateTime, server_default=func.now())
    approved_at = Column(DateTime)
    rejected_at = Column(DateTime)
    executed_at = Column(DateTime)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    event_type = Column(Text, nullable=False)
    source = Column(Text)
    payload = Column(JSONB)
    created_at = Column(DateTime, server_default=func.now())
