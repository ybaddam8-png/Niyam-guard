"""
Step 1 of the pipeline (doc section 3, step 2): "The system understands what actually changed."
Takes raw circular text (already OCR'd/extracted from PDF) and returns structured RuleDelta objects.
"""
import hashlib
from datetime import date
from typing import List
from app.llm_client import call_llm, extract_json
from app.schemas import RuleDelta, ConfidenceLevel

SYSTEM_PROMPT = """You are a policy-analysis extractor for Indian government circulars.
Your ONLY job: find clauses that CHANGE an existing rule (a value, a duration, an eligibility
criterion, a deadline, a required document) and report the old value, new value, and effective
date if stated.

Rules:
- Only report actual CHANGES (old value -> new value). Do not report clauses that merely restate
  existing policy with no change.
- Quote the source sentence VERBATIM from the input text in "source_sentence".
- If wording is ambiguous (e.g. the old value is implied but not explicit, or the effective date
  is missing), set confidence to "low" and explain why in confidence_reason. Do NOT guess a value
  to fill a gap — leave old_value or effective_date as an empty string if genuinely not stated.
- confidence_reason must NEVER be empty, regardless of confidence level. For "high" confidence,
  briefly state what made it unambiguous (e.g. "explicit old and new values stated for both groups").
- If the circular is in a regional language, extract and translate field_name/values to English
  but keep source_sentence in the ORIGINAL language exactly as written.
- In addition to "effective_date" (free text), also output "effective_date_iso" as a strict
  YYYY-MM-DD date, but ONLY when the circular states one unambiguous, specific date (e.g.
  "1st April 2026"). If it says something vague ("with immediate effect", "forthwith") or states
  no date at all, output effective_date_iso as an empty string "" — do NOT guess or approximate a date.
- Output ONLY a JSON array, no prose, no markdown fences. Each element:
  {"field_name": str, "old_value": str, "new_value": str, "effective_date": str or "",
   "effective_date_iso": str (YYYY-MM-DD) or "", "source_sentence": str,
   "confidence": "high"|"medium"|"low", "confidence_reason": str}
- If no rule changes are found, output an empty JSON array: []
"""


def extract_rule_deltas(circular_text: str) -> List[RuleDelta]:
    """Calls the configured LLM and returns validated RuleDelta objects.

    Raises app.llm_client.LLMError if the API call fails or the API key is missing —
    callers (e.g. the FastAPI route) should catch this and return a clear error to the UI
    rather than silently falling back to fake data.
    """
    user_prompt = f"CIRCULAR TEXT:\n---\n{circular_text}\n---"
    raw = call_llm(SYSTEM_PROMPT, user_prompt)
    items = extract_json(raw)
    if not isinstance(items, list):
        items = [items]

    deltas = []
    for item in items:
        # clause_id must be unique PER FACT, not per sentence — a single sentence can
        # state two distinct changes (e.g. "boys' rate: X -> Y, girls' rate: A -> B" in
        # one sentence). Hashing source_sentence alone collided both into the same id,
        # which crashed persistence with a duplicate-key error the first time a circular
        # like that was actually tested. Hashing the full fact keeps genuine re-extraction
        # of the identical fact idempotent while giving distinct facts distinct ids.
        fact_key = f"{item['field_name']}|{item.get('old_value','')}|{item['new_value']}|{item['source_sentence']}"
        clause_id = hashlib.sha256(fact_key.encode("utf-8")).hexdigest()[:16]
        raw_iso = (item.get("effective_date_iso") or "").strip()
        parsed_iso_date = None
        if raw_iso:
            try:
                parsed_iso_date = date.fromisoformat(raw_iso)
            except ValueError:
                # LLM produced something that isn't a real YYYY-MM-DD date. Never guess a
                # correction — leave it null, same "don't fill gaps" rule as everything else here.
                parsed_iso_date = None

        deltas.append(
            RuleDelta(
                clause_id=clause_id,
                field_name=item["field_name"],
                old_value=item.get("old_value", ""),
                new_value=item["new_value"],
                effective_date=item.get("effective_date") or None,
                effective_date_iso=parsed_iso_date,
                source_sentence=item["source_sentence"],
                confidence=ConfidenceLevel(item["confidence"]),
                confidence_reason=item["confidence_reason"],
            )
        )
    return deltas
