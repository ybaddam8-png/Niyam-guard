"""
Pydantic models shared across the pipeline.
These are the actual data contracts between extraction -> diffing -> graph -> audit -> API.
"""
from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RuleDelta(BaseModel):
    """The extracted output of 'what actually changed' in a circular."""
    clause_id: str = Field(..., description="Stable id, e.g. hash of source sentence")
    field_name: str = Field(..., description="What the rule governs, e.g. 'income_certificate_validity_months'")
    old_value: str
    new_value: str
    effective_date: Optional[str] = Field(None, description="ISO date string if stated, else null")
    source_sentence: str = Field(..., description="Verbatim sentence from the circular this was extracted from")
    confidence: ConfidenceLevel
    confidence_reason: str = Field(..., description="Why this confidence level was assigned")


class SystemType(str, Enum):
    PORTAL = "portal"
    SOP = "sop"
    FORM = "form"
    NOTIFICATION = "notification"


class DependentSystem(BaseModel):
    """A system that is supposed to reflect a given rule."""
    system_id: str
    system_type: SystemType
    display_name: str
    current_text: str = Field(..., description="The current stated behavior/text of this system for this rule")
    source_url: Optional[str] = None
    is_illustrative: bool = Field(
        False, description="True if this system's data is a stand-in (no public source exists), must be disclosed"
    )
    scheme_id: Optional[str] = Field(None, description="Which scheme/policy area this system belongs to")
    entity_label: Optional[str] = Field(
        None, description="Which entity/region/office this instance represents, e.g. 'District: Warangal'. "
                           "Systems with no entity_label are grouped as one default entity."
    )


class SyncStatus(str, Enum):
    IN_SYNC = "in_sync"
    OUT_OF_SYNC = "out_of_sync"
    NEEDS_REVIEW = "needs_review"


class MismatchFlag(BaseModel):
    """One dependent system checked against one rule delta."""
    flag_id: str
    rule: RuleDelta
    system: DependentSystem
    status: SyncStatus
    diff_html: str = Field(..., description="Pre-rendered redline HTML (ins/del spans)")
    citizen_impact_score: int = Field(..., ge=0, le=100)
    priority_reason: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class RippleNode(BaseModel):
    system_id: str
    at_risk: bool
    reason: str


class AuditEntry(BaseModel):
    entry_id: str
    action: str
    actor: str
    payload_hash: str
    prev_hash: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
