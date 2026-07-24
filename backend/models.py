import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSON, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.postgres import Base


class SessionStatus(str, Enum):
    CLARIFYING = "clarifying"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    sessions: Mapped[list["Session"]] = relationship(
        "Session", back_populates="user", cascade="all, delete-orphan"
    )
    memory_entries: Mapped[list["MemoryEntry"]] = relationship(
        "MemoryEntry", back_populates="user", cascade="all, delete-orphan"
    )
    personas: Mapped[list["UserPersona"]] = relationship(
        "UserPersona", back_populates="user", cascade="all, delete-orphan"
    )


class UserPersona(Base):
    """V5-D: per-user persona library. Only dynamically RECRUITED experts are
    saved here (core-8 are always available, never saved). One row per
    (user_id, role) — saving the same role twice is a dedup no-op.

    NOTE (V5-D scope): rows are SAVE + DISPLAY only. The cross-session
    suggestion/auto-add logic (which would consume domain_lock_prompt /
    default_level and bump use_count) is DEFERRED — see the M-FIX domain gate.
    """
    __tablename__ = "user_personas"
    __table_args__ = (
        UniqueConstraint("user_id", "role", name="uq_user_persona_user_role"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(120), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    domain: Mapped[str] = mapped_column(String(200), nullable=False)
    domain_lock_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    default_level: Mapped[str] = mapped_column(String(8), nullable=False, default="L1")
    source_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=True
    )
    use_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship("User", back_populates="personas")


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    problem_statement: Mapped[str] = mapped_column(Text, nullable=False)
    complexity: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(
        String(20), default=SessionStatus.CLARIFYING.value
    )
    phase_plan: Mapped[dict | None] = mapped_column(JSON)
    total_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    # v3.0 fields
    roster: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    enriched_problem: Mapped[str | None] = mapped_column(Text, nullable=True)
    termination_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="sessions")
    agent_messages: Mapped[list["AgentMessage"]] = relationship(
        "AgentMessage", back_populates="session", cascade="all, delete-orphan"
    )
    solution_document: Mapped["SolutionDocument | None"] = relationship(
        "SolutionDocument", back_populates="session", uselist=False, cascade="all, delete-orphan"
    )
    ui_mockups: Mapped[list["UiMockup"]] = relationship(
        "UiMockup", back_populates="session", cascade="all, delete-orphan"
    )
    memory_entries: Mapped[list["MemoryEntry"]] = relationship(
        "MemoryEntry", back_populates="session", cascade="all, delete-orphan"
    )
    decisions: Mapped[list["Decision"]] = relationship(
        "Decision", back_populates="session", cascade="all, delete-orphan"
    )


class AgentMessage(Base):
    __tablename__ = "agent_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False
    )
    agent_role: Mapped[str] = mapped_column(String(50), nullable=False)
    phase: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    structured_output: Mapped[dict | None] = mapped_column(JSON)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    tool_calls: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # v3.0 field
    is_private: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    session: Mapped["Session"] = relationship("Session", back_populates="agent_messages")


class SolutionDocument(Base):
    __tablename__ = "solution_documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), unique=True, nullable=False
    )
    structured_content: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    session: Mapped["Session"] = relationship("Session", back_populates="solution_document")


class UiMockup(Base):
    __tablename__ = "ui_mockups"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False
    )
    artifact_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    session: Mapped["Session"] = relationship("Session", back_populates="ui_mockups")


class MemoryEntry(Base):
    __tablename__ = "memory_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    key_entities: Mapped[dict | None] = mapped_column(JSON)
    # Stores sentence-transformer embedding (~384 floats for all-MiniLM-L6-v2)
    embedding: Mapped[list[float] | None] = mapped_column(ARRAY(Float))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship("User", back_populates="memory_entries")
    session: Mapped["Session"] = relationship("Session", back_populates="memory_entries")


# ── v3.0 Models ───────────────────────────────────────────────────────────────

class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_by: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(30), nullable=False, default="proposed")
    provenance: Mapped[str | None] = mapped_column(String(50), nullable=True)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("decisions.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=datetime.utcnow
    )

    session: Mapped["Session"] = relationship("Session", back_populates="decisions")
    superseded_by: Mapped[list["Decision"]] = relationship(
        "Decision", foreign_keys=[supersedes_id],
        primaryjoin="Decision.supersedes_id == Decision.id",
    )
    challenge_rounds: Mapped[list["ChallengeRound"]] = relationship(
        "ChallengeRound", back_populates="decision", cascade="all, delete-orphan"
    )


class ChallengeRound(Base):
    __tablename__ = "challenge_rounds"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    decision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("decisions.id"), nullable=False
    )
    challenger: Mapped[str] = mapped_column(String(100), nullable=False)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=datetime.utcnow
    )

    decision: Mapped["Decision"] = relationship(
        "Decision", back_populates="challenge_rounds"
    )
