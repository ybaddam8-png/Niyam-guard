"""
Real relational schema. Design notes:
- UUIDs (as strings) for all primary keys — avoids leaking row counts via sequential IDs,
  and matches the ids already used in schemas.py (RuleDelta.clause_id etc.) so the
  Pydantic <-> ORM boundary doesn't need translation logic.
- The audit_log table keeps the hash-chain design from the MVP (see AUDIT_LOG design
  note on the model) but now lives in Postgres instead of a separate SQLite file, so a
  single pg_dump backs up everything — flags, users, AND the audit trail together.
- Roles are a plain string column with a CHECK constraint rather than a separate roles
  table — three fixed roles (admin/reviewer/viewer) don't need a join table, and this is
  the deliberately simpler choice most Postgres schemas actually use in practice for a
  small fixed role set.
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Text, Integer, Boolean, DateTime, ForeignKey, CheckConstraint
)
from sqlalchemy.orm import relationship
from app.db import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=gen_uuid)
    username = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    role = Column(String, nullable=False, default="viewer")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        CheckConstraint("role IN ('admin', 'reviewer', 'viewer')", name="valid_role"),
    )


class Circular(Base):
    __tablename__ = "circulars"
    id = Column(String, primary_key=True, default=gen_uuid)
    filename = Column(String, nullable=True)
    raw_text = Column(Text, nullable=False)
    uploaded_by = Column(String, ForeignKey("users.id"), nullable=True)
    uploaded_at = Column(DateTime(timezone=True), default=utcnow)

    rule_deltas = relationship("RuleDeltaRecord", back_populates="circular")


class RuleDeltaRecord(Base):
    __tablename__ = "rule_deltas"
    id = Column(String, primary_key=True, default=gen_uuid)
    circular_id = Column(String, ForeignKey("circulars.id"), nullable=True)
    clause_id = Column(String, nullable=False)
    field_name = Column(String, nullable=False)
    old_value = Column(Text, nullable=False)
    new_value = Column(Text, nullable=False)
    effective_date = Column(String, nullable=True)
    source_sentence = Column(Text, nullable=False)
    confidence = Column(String, nullable=False)
    confidence_reason = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    circular = relationship("Circular", back_populates="rule_deltas")
    flags = relationship("MismatchFlagRecord", back_populates="rule")


class DependentSystemRecord(Base):
    __tablename__ = "dependent_systems"
    id = Column(String, primary_key=True, default=gen_uuid)
    system_type = Column(String, nullable=False)
    display_name = Column(String, nullable=False)
    current_text = Column(Text, nullable=False)
    source_url = Column(String, nullable=True)
    is_illustrative = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        CheckConstraint(
            "system_type IN ('portal', 'sop', 'form', 'notification')", name="valid_system_type"
        ),
    )


class MismatchFlagRecord(Base):
    __tablename__ = "mismatch_flags"
    id = Column(String, primary_key=True, default=gen_uuid)
    rule_id = Column(String, ForeignKey("rule_deltas.id"), nullable=False)
    system_id = Column(String, ForeignKey("dependent_systems.id"), nullable=False)
    status = Column(String, nullable=False)
    diff_html = Column(Text, nullable=False)
    citizen_impact_score = Column(Integer, nullable=False)
    priority_reason = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    rule = relationship("RuleDeltaRecord", back_populates="flags")
    system = relationship("DependentSystemRecord")
    approvals = relationship("ApprovalRecord", back_populates="flag")

    __table_args__ = (
        CheckConstraint(
            "status IN ('in_sync', 'out_of_sync', 'needs_review')", name="valid_sync_status"
        ),
    )


class ApprovalRecord(Base):
    __tablename__ = "approvals"
    id = Column(String, primary_key=True, default=gen_uuid)
    flag_id = Column(String, ForeignKey("mismatch_flags.id"), nullable=False)
    approver_id = Column(String, ForeignKey("users.id"), nullable=False)
    notification_text = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    flag = relationship("MismatchFlagRecord", back_populates="approvals")
    approver = relationship("User")


class AuditLogEntry(Base):
    """Hash-chained, same tamper-evidence design as the MVP's audit.py, now in Postgres.
    See app/audit_service.py for the chain logic — this class is intentionally dumb storage."""
    __tablename__ = "audit_log"
    id = Column(String, primary_key=True, default=gen_uuid)
    action = Column(String, nullable=False)
    actor_user_id = Column(String, ForeignKey("users.id"), nullable=True)
    actor_label = Column(String, nullable=False)  # denormalized username, survives user deletion
    payload = Column(Text, nullable=False)
    payload_hash = Column(String, nullable=False)
    prev_hash = Column(String, nullable=False)
    timestamp = Column(DateTime(timezone=True), default=utcnow)
