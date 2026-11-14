"""Attributed passage judgments; no automatic promotion from relevance to support."""

import hashlib
from datetime import datetime
from typing import Any


def validate_judgment(storage: Any, record: dict[str, Any]) -> None:
    required = ("claim", "passage", "reason", "reviewer", "judgment_method", "reviewed_at")
    if not isinstance(record, dict) or any(
        not isinstance(record.get(k), str) or not record[k].strip() for k in required
    ):
        raise ValueError(
            "Judgment requires claim, exact passage, reason, reviewer, method and date"
        )
    if record.get("reviewer_status") not in ("human_reviewed", "assistant_reviewed"):
        raise ValueError("Declare reviewer_status explicitly")
    if record.get("judgment") not in ("supports", "contradicts", "uncertain", "does_not_support"):
        raise ValueError("Invalid judgment")
    try:
        datetime.fromisoformat(record["reviewed_at"])
    except ValueError as exc:
        raise ValueError("reviewed_at must be a valid ISO date or datetime") from exc
    for key in ("document_id", "chunk_index", "snapshot_id"):
        if type(record.get(key)) is not int:
            raise ValueError(f"{key} must be an integer")
    passage = storage.get_passage(record["document_id"], record["chunk_index"])
    if passage is None:
        raise ValueError("Unavailable or uninspected passage")
    if (
        record["snapshot_id"] != passage["snapshot_id"]
        or record.get("sha256") != passage["sha256"]
    ):
        raise ValueError("Snapshot/document identity mismatch")
    if record["passage"] not in passage["text"]:
        raise ValueError("Quoted passage does not occur in the inspected chunk")
    record["passage_sha256"] = hashlib.sha256(passage["text"].encode()).hexdigest()
    record["document_completeness"] = passage["document_completeness"]
    record["inspection_status"] = "passage_inspected_by_declared_reviewer"
    record["source_support"] = (
        "human_reviewed_support"
        if record["reviewer_status"] == "human_reviewed" and record["judgment"] == "supports"
        else "source_support_unverified"
    )


def summarize_judgments(records: list[dict[str, Any]], claim: str) -> dict[str, Any]:
    matching = [r for r in records if r["claim"] == claim]
    contradiction = any(r["judgment"] == "contradicts" for r in matching)
    uncertainty = any(r["judgment"] == "uncertain" for r in matching)
    supported = any(r["source_support"] == "human_reviewed_support" for r in matching)
    return {
        "claim": claim,
        "judgments": matching,
        "status": "contradictory"
        if contradiction
        else "uncertain"
        if uncertainty
        else "human_reviewed_support"
        if supported
        else "source_support_unverified",
    }
