"""Attributed passage judgments; no automatic promotion from relevance to support.

A judgment is an attributed claim about one exact passage: which claim,
which quoted passage, which reviewer, which method, when. Three rules keep
a judgment honest (#50, MTR-020):

- **Span grounding.** A ``supports`` judgment must pin the exact grounding
  span inside its chunk (``span_start``/``span_end``), and the span text
  must equal the quoted passage. Term overlap is not entailment, and a
  judgment with no verifiable span cannot be ``supports``.
- **Reviewer authentication.** The reviewer must resolve to a known
  identity in ``docs/reviewers.yaml`` (the repo's own seed/config), and
  the identity's kind must match the attested ``reviewer_status``: only a
  human identity can attest ``human_reviewed``. The stored record carries
  the resolved identity (``reviewer_id``/``reviewer_kind``), not just the
  supplied name.
- **Invalidation.** A judgment is history, not live evidence, once its
  source text changes: ``storage`` marks it ``superseded`` (never deleted)
  and ``summarize_judgments`` reports superseded records separately, so a
  stale ``supports`` can never read as live support.
"""

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

# The method registry (#50, step 2): a judgment_method must name one of
# these procedures. Free text cannot name a method, so it cannot be checked.
# No entry here proves entailment on its own; the span is the checkable
# basis, and the method records how the reviewer arrived at the judgment.
JUDGMENT_METHODS: dict[str, str] = {
    "exact passage inspection": (
        "The reviewer read the exact quoted passage in its chunk and "
        "attests the judgment from that reading; the quote is verified, "
        "entailment is not proved by the method alone."
    ),
    "span-grounded inspection": (
        "The reviewer pinned the exact grounding span inside the chunk "
        "that the claim rests on; the span is verified against the chunk "
        "text, so the grounding is machine-checkable."
    ),
}

REVIEWERS_PATH = Path(__file__).resolve().parents[2] / "docs" / "reviewers.yaml"

# Reviewer kinds and which reviewer_status each may attest. A human
# identity attests human review; an assistant or synthetic identity
# attests assistant review. No kind attests the other side's status:
# the status says who reviewed, so a mismatch is a false attestation.
REVIEWER_KIND_STATUSES: dict[str, tuple[str, ...]] = {
    "human": ("human_reviewed",),
    "assistant": ("assistant_reviewed",),
    "synthetic": ("assistant_reviewed",),
}

# Status precedence when one status must stand for several claims:
# a contradiction anywhere beats uncertainty, which beats support.
SUPPORT_STATUS_ORDER: tuple[str, ...] = (
    "contradictory",
    "uncertain",
    "human_reviewed_support",
    "source_support_unverified",
)


def load_reviewers(path: Path | str = REVIEWERS_PATH) -> dict[str, dict[str, str]]:
    """The reviewer allowlist as id -> identity, or fail closed when absent."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("reviewers"), list):
        raise ValueError(  # noqa: TRY004 -- malformed allowlist is a record error
            f"Reviewer allowlist {path} must list reviewers"
        )
    reviewers: dict[str, dict[str, str]] = {}
    for entry in raw["reviewers"]:
        if not isinstance(entry, dict):
            raise ValueError(  # noqa: TRY004 -- malformed allowlist is a record error
                "Each reviewer entry must be an object"
            )
        reviewer_id = entry.get("id")
        kind = entry.get("kind")
        if not isinstance(reviewer_id, str) or not reviewer_id.strip():
            raise ValueError("Each reviewer entry needs a non-empty id")
        if kind not in REVIEWER_KIND_STATUSES:
            raise ValueError(f"Reviewer {reviewer_id!r} has unknown kind {kind!r}")
        reviewers[reviewer_id] = {"id": reviewer_id, "kind": str(kind)}
    if not reviewers:
        raise ValueError(f"Reviewer allowlist {path} is empty")
    return reviewers


def resolve_reviewer(reviewer: str, reviewer_status: str) -> dict[str, str]:
    """Resolve a reviewer name to a known identity, or raise ValueError.

    Why: a free-text reviewer is self-declared, so anyone can declare
    ``human_reviewed``. The allowlist binds the name to an identity whose
    kind matches the attested status; anything else is rejected, not
    recorded.
    """
    identity = load_reviewers().get(reviewer)
    if identity is None:
        raise ValueError(f"Unknown reviewer {reviewer!r}: not in docs/reviewers.yaml")
    allowed = REVIEWER_KIND_STATUSES[identity["kind"]]
    if reviewer_status not in allowed:
        raise ValueError(
            f"Reviewer {reviewer!r} (kind {identity['kind']}) cannot attest "
            f"{reviewer_status}; allowed: {', '.join(allowed)}"
        )
    return identity


def _validate_span(record: dict[str, Any], chunk_text: str) -> None:
    """Verify the grounding span, when one is claimed or required.

    Why: the span is the machine-checkable support basis. A ``supports``
    judgment without one is a bare assertion, so it cannot be recorded;
    a span that does not pin exactly the quoted passage is a false
    grounding, so it is rejected for any judgment value.
    """
    start = record.get("span_start")
    end = record.get("span_end")
    if record.get("judgment") != "supports" and start is None and end is None:
        return
    if type(start) is not int or type(end) is not int:
        raise ValueError("A supports judgment requires integer span_start/span_end")
    if not 0 <= start < end <= len(chunk_text):
        raise ValueError("span_start/span_end must name a non-empty span inside the chunk")
    if chunk_text[start:end] != record["passage"]:
        raise ValueError("The grounding span must be exactly the quoted passage")


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
    if record.get("judgment_method") not in JUDGMENT_METHODS:
        raise ValueError(
            "judgment_method must name a registered method: "
            + ", ".join(sorted(JUDGMENT_METHODS))
        )
    identity = resolve_reviewer(str(record["reviewer"]), str(record["reviewer_status"]))
    _validate_span(record, str(passage["text"]))
    record["reviewer_id"] = identity["id"]
    record["reviewer_kind"] = identity["kind"]
    record["passage_sha256"] = hashlib.sha256(passage["text"].encode()).hexdigest()
    record["document_completeness"] = passage["document_completeness"]
    record["inspection_status"] = "passage_inspected_by_declared_reviewer"
    record["source_support"] = (
        "human_reviewed_support"
        if record["reviewer_status"] == "human_reviewed" and record["judgment"] == "supports"
        else "source_support_unverified"
    )


def summarize_judgments(records: list[dict[str, Any]], claim: str) -> dict[str, Any]:
    """Summarize one claim's judgments; superseded records are history.

    Why the split: a superseded ``supports`` is evidence about the old
    source text, not the current one. The status is computed over live
    judgments only, and superseded records are listed alongside it, so a
    stale support can never read as live support.
    """
    matching = [r for r in records if r["claim"] == claim]
    live = [r for r in matching if r.get("status") != "superseded"]
    superseded = [r for r in matching if r.get("status") == "superseded"]
    contradiction = any(r["judgment"] == "contradicts" for r in live)
    uncertainty = any(r["judgment"] == "uncertain" for r in live)
    supported = any(r["source_support"] == "human_reviewed_support" for r in live)
    return {
        "claim": claim,
        "judgments": live,
        "superseded": superseded,
        "superseded_count": len(superseded),
        "status": "contradictory"
        if contradiction
        else "uncertain"
        if uncertainty
        else "human_reviewed_support"
        if supported
        else "source_support_unverified",
    }


def worst_support_status(statuses: list[str]) -> str:
    """The worst case across per-claim statuses, by SUPPORT_STATUS_ORDER."""
    for status in SUPPORT_STATUS_ORDER:
        if status in statuses:
            return status
    return "source_support_unverified"
