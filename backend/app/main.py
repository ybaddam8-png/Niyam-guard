"""
NiyamGuard AI backend — production hardening pass.
Every route except /health and /auth/login requires a valid JWT. Role hierarchy:
viewer < reviewer < admin (see app/auth.py).
"""
import json
import logging
from collections import defaultdict
from typing import List, Optional
from fastapi import FastAPI, HTTPException, UploadFile, File, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
import networkx as nx

from app import config, pdf_utils, audit_service
from app.db import get_db
from app.models import User, Circular, RuleDeltaRecord, DependentSystemRecord, MismatchFlagRecord, ApprovalRecord
from app.auth import get_current_user, require_role
from app.security import verify_password, create_access_token
from app.extraction import extract_rule_deltas
from app.diffing import make_redline_html, similarity_ratio
from app.graph import build_dependency_graph, trace_ripple, citizen_impact_score
from app.schemas import RuleDelta, DependentSystem, MismatchFlag, SyncStatus
from app.llm_client import LLMError
from app.logging_config import configure_logging, RequestIdMiddleware, get_request_id

configure_logging()
logger = logging.getLogger("niyamguard.startup")

if not config.JWT_SECRET_KEY:
    raise RuntimeError(
        "JWT_SECRET_KEY is not set. Generate one: python3 -c \"import secrets; print(secrets.token_hex(32))\""
    )
if not config.ALLOWED_ORIGINS:
    logger.warning("ALLOWED_ORIGINS is empty — no browser frontend will be able to call this API.")

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="NiyamGuard AI", version="0.2.0-production")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(RequestIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Global error handling
# ---------------------------------------------------------------------------
@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError):
    request_id = get_request_id()
    logging.getLogger("niyamguard.error").exception(
        f"Database constraint violation on {request.method} {request.url.path} [{request_id}]"
    )
    return JSONResponse(
        status_code=409,
        content={
            "detail": "A database constraint was violated (e.g. a duplicate entry). "
                      "This has been logged.",
            "request_id": request_id,
        },
    )


# NOTE: there is deliberately no @app.exception_handler(Exception) here. Starlette's
# build_middleware_stack() special-cases any handler registered for the bare Exception
# class (or status code 500): it's pulled out and moved to ServerErrorMiddleware, which
# wraps ALL user middleware including RequestIdMiddleware — not the other way around.
# By the time such a handler would run, RequestIdMiddleware's contextvar has already
# been reset and its send wrapper is out of the call chain, so it could never actually
# carry the real request_id. The real fix lives inside RequestIdMiddleware itself
# (see app/logging_config.py), which runs INSIDE the exception's propagation path.


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    expires_in_minutes: int


@app.post("/auth/login", response_model=LoginResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == req.username).first()
    if not user or not user.is_active or not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = create_access_token(user.id, user.username, user.role)
    return LoginResponse(
        access_token=token, role=user.role, expires_in_minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES
    )


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "viewer"


@app.post("/auth/users", dependencies=[Depends(require_role("admin"))])
def create_user(req: CreateUserRequest, db: Session = Depends(get_db)):
    if req.role not in ("admin", "reviewer", "viewer"):
        raise HTTPException(status_code=422, detail="role must be admin, reviewer, or viewer")
    if db.query(User).filter(User.username == req.username).first():
        raise HTTPException(status_code=409, detail="username already exists")
    from app.security import hash_password
    user = User(username=req.username, hashed_password=hash_password(req.password), role=req.role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"id": user.id, "username": user.username, "role": user.role}


# ---------------------------------------------------------------------------
# Circular ingestion + extraction (reviewer or admin)
# ---------------------------------------------------------------------------
class ExtractTextRequest(BaseModel):
    circular_text: str


def _persist_deltas(db: Session, circular: Circular, deltas: List[RuleDelta]) -> None:
    for d in deltas:
        existing = db.query(RuleDeltaRecord).filter(RuleDeltaRecord.id == d.clause_id).first()
        if existing:
            continue
        db.add(RuleDeltaRecord(
            id=d.clause_id,
            circular_id=circular.id if circular else None,
            clause_id=d.clause_id,
            field_name=d.field_name,
            old_value=d.old_value,
            new_value=d.new_value,
            effective_date=d.effective_date,
            source_sentence=d.source_sentence,
            confidence=d.confidence.value,
            confidence_reason=d.confidence_reason,
        ))
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            continue
    db.commit()


@app.post("/circulars/extract", response_model=List[RuleDelta])
@limiter.limit(config.EXTRACTION_RATE_LIMIT)
def extract_from_text(
    request: Request,
    req: ExtractTextRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("reviewer")),
):
    try:
        deltas = extract_rule_deltas(req.circular_text)
    except LLMError as e:
        raise HTTPException(status_code=502, detail=str(e))

    circular = Circular(raw_text=req.circular_text, uploaded_by=user.id)
    db.add(circular)
    db.commit()
    db.refresh(circular)
    _persist_deltas(db, circular, deltas)

    audit_service.log_action(
        db, action="circular_extracted", actor_user_id=user.id, actor_label=user.username,
        payload=json.dumps({"circular_id": circular.id, "num_deltas": len(deltas)}),
    )
    return deltas


@app.post("/circulars/extract-pdf", response_model=List[RuleDelta])
@limiter.limit(config.EXTRACTION_RATE_LIMIT)
async def extract_from_pdf(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_role("reviewer")),
):
    file_bytes = await file.read()
    try:
        text = pdf_utils.extract_text_from_pdf(file_bytes)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    try:
        deltas = extract_rule_deltas(text)
    except LLMError as e:
        raise HTTPException(status_code=502, detail=str(e))

    circular = Circular(filename=file.filename, raw_text=text, uploaded_by=user.id)
    db.add(circular)
    db.commit()
    db.refresh(circular)
    _persist_deltas(db, circular, deltas)

    audit_service.log_action(
        db, action="circular_extracted", actor_user_id=user.id, actor_label=user.username,
        payload=json.dumps({"circular_id": circular.id, "filename": file.filename, "num_deltas": len(deltas)}),
    )
    return deltas


# ---------------------------------------------------------------------------
# Check (reviewer or admin) — persists systems + flags, not just ephemeral response
# ---------------------------------------------------------------------------
class CheckRequest(BaseModel):
    rule: RuleDelta
    systems: List[DependentSystem]
    sync_similarity_threshold: float = 0.85


class CheckResponse(BaseModel):
    flags: List[MismatchFlag]
    ripple: list


def _persist_system(db: Session, s: DependentSystem) -> DependentSystemRecord:
    row = db.query(DependentSystemRecord).filter(DependentSystemRecord.id == s.system_id).first()
    if row:
        row.current_text = s.current_text
        row.display_name = s.display_name
        row.is_illustrative = s.is_illustrative
        row.scheme_id = s.scheme_id
        row.entity_label = s.entity_label
    else:
        row = DependentSystemRecord(
            id=s.system_id, system_type=s.system_type.value, display_name=s.display_name,
            current_text=s.current_text, source_url=s.source_url, is_illustrative=s.is_illustrative,
            scheme_id=s.scheme_id, entity_label=s.entity_label,
        )
        db.add(row)
    db.commit()
    return row


@app.post("/check", response_model=CheckResponse)
def check_systems(
    req: CheckRequest, db: Session = Depends(get_db), user: User = Depends(require_role("reviewer"))
):
    rule_row = db.query(RuleDeltaRecord).filter(RuleDeltaRecord.id == req.rule.clause_id).first()
    if not rule_row:
        rule_row = RuleDeltaRecord(
            id=req.rule.clause_id, circular_id=None, clause_id=req.rule.clause_id,
            field_name=req.rule.field_name, old_value=req.rule.old_value, new_value=req.rule.new_value,
            effective_date=req.rule.effective_date, source_sentence=req.rule.source_sentence,
            confidence=req.rule.confidence.value, confidence_reason=req.rule.confidence_reason,
        )
        db.add(rule_row)
        db.commit()

    for s in req.systems:
        _persist_system(db, s)

    graph = build_dependency_graph(req.systems)

    statuses: dict[str, SyncStatus] = {}
    for system in req.systems:
        ratio = similarity_ratio(req.rule.new_value, system.current_text)
        if req.rule.new_value.strip().lower() in system.current_text.strip().lower():
            status = SyncStatus.IN_SYNC
        elif ratio >= req.sync_similarity_threshold:
            status = SyncStatus.NEEDS_REVIEW
        else:
            status = SyncStatus.OUT_OF_SYNC
        statuses[system.system_id] = status

    out_of_sync_ids = [sid for sid, st in statuses.items() if st == SyncStatus.OUT_OF_SYNC]
    ripple = trace_ripple(graph, out_of_sync_ids)
    downstream_risk_count = {r.system_id: 0 for r in ripple}
    for system in req.systems:
        if system.system_id in graph:
            downstream_risk_count[system.system_id] = sum(
                1 for d in nx.descendants(graph, system.system_id)
                if any(r.system_id == d and r.at_risk for r in ripple)
            )

    flags: List[MismatchFlag] = []
    for system in req.systems:
        status = statuses[system.system_id]
        score, reason = citizen_impact_score(status, downstream_risk_count.get(system.system_id, 0))
        diff_html = make_redline_html(system.current_text, req.rule.new_value)
        flag = MismatchFlag(
            flag_id=__import__("uuid").uuid4().hex,
            rule=req.rule, system=system, status=status,
            diff_html=diff_html, citizen_impact_score=score, priority_reason=reason,
        )
        flags.append(flag)
        db.add(MismatchFlagRecord(
            id=flag.flag_id, rule_id=req.rule.clause_id, system_id=system.system_id,
            status=status.value, diff_html=diff_html, citizen_impact_score=score, priority_reason=reason,
        ))
        db.commit()
        audit_service.log_action(
            db, action="mismatch_flagged", actor_user_id=user.id, actor_label=user.username,
            payload=flag.model_dump_json(),
        )

    flags.sort(key=lambda f: f.citizen_impact_score, reverse=True)
    return CheckResponse(flags=flags, ripple=[r.model_dump() for r in ripple])


# ---------------------------------------------------------------------------
# Scale View (viewer or above) — same rule, many entities: which are lagging
# ---------------------------------------------------------------------------
class ScaleViewEntity(BaseModel):
    entity_label: str
    systems_checked: int
    systems_out_of_sync: int
    worst_status: SyncStatus
    max_citizen_impact_score: int


class ScaleViewResponse(BaseModel):
    rule_id: str
    field_name: str
    total_entities: int
    entities_with_issues: int
    entities: List[ScaleViewEntity]


_STATUS_SEVERITY = {SyncStatus.IN_SYNC: 0, SyncStatus.NEEDS_REVIEW: 1, SyncStatus.OUT_OF_SYNC: 2}


@app.get("/scale-view/{rule_id}", response_model=ScaleViewResponse,
         dependencies=[Depends(require_role("viewer"))])
def scale_view(rule_id: str, db: Session = Depends(get_db)):
    rule_row = db.query(RuleDeltaRecord).filter(RuleDeltaRecord.id == rule_id).first()
    if not rule_row:
        raise HTTPException(status_code=404, detail="rule not found")

    rows = (
        db.query(MismatchFlagRecord, DependentSystemRecord)
        .join(DependentSystemRecord, MismatchFlagRecord.system_id == DependentSystemRecord.id)
        .filter(MismatchFlagRecord.rule_id == rule_id)
        .all()
    )

    by_entity: dict[str, list] = defaultdict(list)
    for flag, system in rows:
        by_entity[system.entity_label or "unassigned"].append((flag, system))

    entities: List[ScaleViewEntity] = []
    for entity_label, entity_rows in by_entity.items():
        statuses = [SyncStatus(f.status) for f, s in entity_rows]
        worst = max(statuses, key=lambda st: _STATUS_SEVERITY[st])
        entities.append(ScaleViewEntity(
            entity_label=entity_label,
            systems_checked=len(entity_rows),
            systems_out_of_sync=sum(1 for st in statuses if st == SyncStatus.OUT_OF_SYNC),
            worst_status=worst,
            max_citizen_impact_score=max(f.citizen_impact_score for f, s in entity_rows),
        ))

    entities.sort(key=lambda e: e.max_citizen_impact_score, reverse=True)

    return ScaleViewResponse(
        rule_id=rule_id,
        field_name=rule_row.field_name,
        total_entities=len(entities),
        entities_with_issues=sum(1 for e in entities if e.systems_out_of_sync > 0),
        entities=entities,
    )


# ---------------------------------------------------------------------------
# Approvals (reviewer or admin) — never auto-sends, only logs the human decision
# ---------------------------------------------------------------------------
class ApprovalRequest(BaseModel):
    flag_id: str
    notification_text: Optional[str] = None


@app.post("/approvals")
def record_approval(
    req: ApprovalRequest, db: Session = Depends(get_db), user: User = Depends(require_role("reviewer"))
):
    flag = db.query(MismatchFlagRecord).filter(MismatchFlagRecord.id == req.flag_id).first()
    if not flag:
        raise HTTPException(status_code=404, detail="flag_id not found")
    approval = ApprovalRecord(flag_id=req.flag_id, approver_id=user.id, notification_text=req.notification_text)
    db.add(approval)
    db.commit()
    db.refresh(approval)
    entry = audit_service.log_action(
        db,
        action="human_approved_notification" if req.notification_text else "human_approved_fix",
        actor_user_id=user.id, actor_label=user.username,
        payload=json.dumps({"flag_id": req.flag_id, "notification_text": req.notification_text}),
    )
    return {"approval_id": approval.id, "audit_entry_id": entry.id, "timestamp": entry.timestamp.isoformat()}


# ---------------------------------------------------------------------------
# Audit (any authenticated user — viewer and up — transparency is the point)
# ---------------------------------------------------------------------------
@app.get("/audit", dependencies=[Depends(require_role("viewer"))])
def get_audit_log(db: Session = Depends(get_db)):
    from app.models import AuditLogEntry
    rows = db.query(AuditLogEntry).order_by(AuditLogEntry.timestamp.asc()).all()
    return [
        {
            "id": r.id, "action": r.action, "actor": r.actor_label, "payload": r.payload,
            "payload_hash": r.payload_hash, "prev_hash": r.prev_hash, "timestamp": r.timestamp.isoformat(),
        }
        for r in rows
    ]


@app.get("/audit/verify", dependencies=[Depends(require_role("viewer"))])
def verify_audit_chain(db: Session = Depends(get_db)):
    ok, message = audit_service.verify_chain(db)
    return {"chain_intact": ok, "message": message}
