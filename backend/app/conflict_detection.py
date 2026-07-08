"""
Doc feature: 'Conflict Detection Across Circulars — where two circulars affect the same
rule with different effective dates, the system identifies which one currently supersedes
the other.'

Strict by design: this only resolves which rule currently governs when BOTH rules have a
real parsed_effective_date (see RuleDeltaRecord.parsed_effective_date, populated only from
extraction.py's effective_date_iso — which itself is only ever set for unambiguous stated
dates, never guessed). Anything else is recorded as 'ambiguous_missing_date' and routed to
human review, consistent with this codebase's rule of never silently guessing where a
circular is unclear.
"""
from datetime import date
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session
from app.models import RuleDeltaRecord, RuleConflictRecord


def _resolve(rule_a: RuleDeltaRecord, rule_b: RuleDeltaRecord, today: date) -> Tuple[str, str, Optional[str]]:
    """Returns (resolution, resolution_reason, governing_rule_id_or_None)."""
    date_a, date_b = rule_a.parsed_effective_date, rule_b.parsed_effective_date

    if date_a is None or date_b is None:
        missing = []
        if date_a is None:
            missing.append(f"rule {rule_a.id} has no parsed effective date")
        if date_b is None:
            missing.append(f"rule {rule_b.id} has no parsed effective date")
        return (
            "ambiguous_missing_date",
            "Cannot determine which circular currently governs: " + "; ".join(missing) +
            ". Routed to human review rather than guessed.",
            None,
        )

    a_in_force = date_a <= today
    b_in_force = date_b <= today

    if not a_in_force and not b_in_force:
        return (
            "both_future",
            f"Neither rule has taken effect yet (rule {rule_a.id} effective {date_a}, rule "
            f"{rule_b.id} effective {date_b}). Whatever rule applied before either circular "
            f"remains in force until the earlier of these two dates arrives.",
            None,
        )

    if a_in_force and (not b_in_force or date_a >= date_b):
        return (
            "a_governs",
            f"Rule {rule_a.id} (effective {date_a}) is the most recent rule already in force, "
            f"superseding rule {rule_b.id} (effective {date_b}).",
            rule_a.id,
        )
    return (
        "b_governs",
        f"Rule {rule_b.id} (effective {date_b}) is the most recent rule already in force, "
        f"superseding rule {rule_a.id} (effective {date_a}).",
        rule_b.id,
    )


def detect_conflicts_for_new_rule(
    db: Session, new_rule: RuleDeltaRecord, today: Optional[date] = None
) -> List[RuleConflictRecord]:
    """Call once, right after a genuinely new RuleDeltaRecord is first persisted. Finds
    every existing rule with the same field_name from a DIFFERENT circular and records a
    conflict for each pair not already recorded. Two clauses of the SAME circular sharing a
    field_name is a different problem (an internal contradiction in one document) and is
    deliberately out of scope here."""
    if today is None:
        today = date.today()

    candidates = (
        db.query(RuleDeltaRecord)
        .filter(RuleDeltaRecord.field_name == new_rule.field_name)
        .filter(RuleDeltaRecord.id != new_rule.id)
        .all()
    )
    others = [
        o for o in candidates
        if not (new_rule.circular_id is not None and o.circular_id == new_rule.circular_id)
    ]

    created: List[RuleConflictRecord] = []
    for other in others:
        already_recorded = (
            db.query(RuleConflictRecord)
            .filter(
                ((RuleConflictRecord.rule_a_id == new_rule.id) & (RuleConflictRecord.rule_b_id == other.id))
                | ((RuleConflictRecord.rule_a_id == other.id) & (RuleConflictRecord.rule_b_id == new_rule.id))
            )
            .first()
        )
        if already_recorded:
            continue

        resolution, reason, governing_id = _resolve(new_rule, other, today)
        record = RuleConflictRecord(
            field_name=new_rule.field_name,
            rule_a_id=new_rule.id,
            rule_b_id=other.id,
            governing_rule_id=governing_id,
            resolution=resolution,
            resolution_reason=reason,
        )
        db.add(record)
        created.append(record)

    if created:
        db.commit()
    return created
