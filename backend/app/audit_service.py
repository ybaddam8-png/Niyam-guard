"""
Same tamper-evidence design as the MVP's audit.py, ported to Postgres. One writer
(this app), one chain, one table — recomputing every hash from stored fields and
checking prev_hash linkage detects any historical tampering.
"""
import hashlib
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models import AuditLogEntry, gen_uuid

GENESIS_HASH = "0" * 64


def _last_hash(db: Session) -> str:
    last = db.query(AuditLogEntry).order_by(AuditLogEntry.timestamp.desc()).first()
    return last.payload_hash if last else GENESIS_HASH


def log_action(db: Session, action: str, actor_user_id: str | None, actor_label: str, payload: str) -> AuditLogEntry:
    prev_hash = _last_hash(db)
    entry_id = gen_uuid()
    timestamp = datetime.now(timezone.utc)
    payload_hash = hashlib.sha256(
        f"{entry_id}|{action}|{actor_label}|{payload}|{timestamp.isoformat()}|{prev_hash}".encode("utf-8")
    ).hexdigest()
    entry = AuditLogEntry(
        id=entry_id,
        action=action,
        actor_user_id=actor_user_id,
        actor_label=actor_label,
        payload=payload,
        payload_hash=payload_hash,
        prev_hash=prev_hash,
        timestamp=timestamp,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def verify_chain(db: Session) -> tuple[bool, str]:
    rows = db.query(AuditLogEntry).order_by(AuditLogEntry.timestamp.asc()).all()
    expected_prev = GENESIS_HASH
    for row in rows:
        recomputed = hashlib.sha256(
            f"{row.id}|{row.action}|{row.actor_label}|{row.payload}|"
            f"{row.timestamp.isoformat()}|{row.prev_hash}".encode("utf-8")
        ).hexdigest()
        if row.prev_hash != expected_prev:
            return False, f"chain broken at entry {row.id}: prev_hash mismatch"
        if recomputed != row.payload_hash:
            return False, f"entry {row.id} was tampered with: hash mismatch"
        expected_prev = row.payload_hash
    return True, f"{len(rows)} entries verified, chain intact"
