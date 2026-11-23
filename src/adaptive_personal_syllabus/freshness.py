"""Live-source freshness (#54, MTR-018).

A refresh observation says one of seven things about a source; this module
turns the stored observations into the freshness state every consumer
(planner, `corpus stats`, `corpus passage`) reports. It never writes.

States
------
- ``fresh`` — the stored document bytes were re-read within the source's
  freshness bound (`max_age_hours`, default 168).
- ``stale`` — the on-disk bytes changed since ingest (the stored snapshot
  holds the old bytes), or the last good retrieval is older than the bound.
  A stale source stays usable; it is never silently presented as current.
- ``missing`` — the latest observation is ``deleted``: the file is gone.
- ``failed`` — the latest observation is ``timeout`` / ``rate_limited`` /
  ``error``: the prior version stays usable-but-stale with its last-good
  ``retrieved_at``.
- ``revoked`` — the latest observation is ``revoked``: the source is present
  but no longer admitted, and the planner excludes it until re-admitted.
- ``unknown`` — no source record exists: the source was ingested but never
  refreshed, so no freshness claim can be made either way.

A refresh never promotes a candidate to support — only a human judgment
does (#50). Freshness is time-varying observation, so it is reported
alongside a plan, never inside the plan fingerprint.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .storage import Storage

FRESHNESS_STATES = ("fresh", "stale", "missing", "failed", "revoked", "unknown")

# A plan is generated from a stale snapshot when any of its documents is in
# one of these states; `unknown` is not stale, it is unmeasured.
STALE_SNAPSHOT_STATES = ("stale", "failed", "missing", "revoked")

# Candidate documents the planner must not select from.
EXCLUDED_STATES = ("missing", "revoked")


def _parse_time(value: str | None) -> datetime | None:
    """An ISO-8601 timestamp as aware UTC, or None when absent/unparseable."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def source_freshness(
    storage: Storage,
    *,
    root_path: str,
    rel_path: str,
    document_sha256: str,
    now: datetime | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """The freshness state of one stored document against its live source.

    `document_sha256` is the sha of the bytes the snapshot holds. The state
    compares that against the latest refresh observation for the same
    (root_path, rel_path) source identity.
    """
    moment = now or datetime.now(tz=UTC)
    record = storage.find_source_record(root_path, rel_path, conn=conn)
    if record is None:
        return {
            "state": "unknown",
            "reason": "never_refreshed",
            "retrieved_at": None,
            "last_good_retrieved_at": None,
            "source_version": None,
            "outcome": None,
            "max_age_hours": None,
        }
    max_age_hours = int(record["max_age_hours"])
    latest = storage.latest_source_version(int(record["id"]), conn=conn)
    content = storage.latest_content_version(int(record["id"]), conn=conn)
    last_good_at = (
        str(content["retrieved_at"]) if content is not None else None
    )
    if latest is None:
        # A record with no observation yet: created, never successfully read.
        return {
            "state": "unknown",
            "reason": "never_refreshed",
            "retrieved_at": None,
            "last_good_retrieved_at": None,
            "source_version": None,
            "outcome": None,
            "max_age_hours": max_age_hours,
        }
    outcome = str(latest["outcome"])
    base: dict[str, Any] = {
        "retrieved_at": str(latest["retrieved_at"]),
        "last_good_retrieved_at": last_good_at,
        "source_version": str(latest["source_version"]),
        "outcome": outcome,
        "max_age_hours": max_age_hours,
    }
    if outcome == "deleted":
        return {**base, "state": "missing", "reason": "deleted"}
    if outcome == "revoked":
        return {**base, "state": "revoked", "reason": "admission_revoked"}
    if outcome in ("timeout", "rate_limited", "error"):
        return {**base, "state": "failed", "reason": outcome}
    # A content observation: same bytes as the snapshot, and how old?
    if content is None or str(content["sha256"]) != document_sha256:
        return {**base, "state": "stale", "reason": "content_changed"}
    retrieved_at = _parse_time(str(content["retrieved_at"]))
    if retrieved_at is None:
        return {**base, "state": "unknown", "reason": "unparseable_retrieved_at"}
    age_hours = (moment - retrieved_at).total_seconds() / 3600
    if age_hours > max_age_hours:
        return {**base, "state": "stale", "reason": "max_age_exceeded"}
    return {**base, "state": "fresh", "reason": "within_bound"}


def summarize_snapshot_freshness(
    storage: Storage,
    *,
    snapshot_id: int,
    now: datetime | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Freshness for every document in a snapshot, plus counts by state."""
    moment = now or datetime.now(tz=UTC)
    keys = storage.list_snapshot_source_keys(snapshot_id, conn=conn)
    sources: list[dict[str, Any]] = []
    counts: dict[str, int] = {state: 0 for state in FRESHNESS_STATES}
    for key in keys:
        state = source_freshness(
            storage,
            root_path=str(key["root_path"]),
            rel_path=str(key["rel_path"]),
            document_sha256=str(key["sha256"]),
            now=moment,
            conn=conn,
        )
        counts[str(state["state"])] += 1
        sources.append(
            {
                "document_id": int(key["document_id"]),
                "rel_path": str(key["rel_path"]),
                "state": str(state["state"]),
                "reason": str(state["reason"]),
                "retrieved_at": state["retrieved_at"],
                "last_good_retrieved_at": state["last_good_retrieved_at"],
                "source_version": state["source_version"],
                "outcome": state["outcome"],
                "max_age_hours": state["max_age_hours"],
            }
        )
    stale = any(s["state"] in STALE_SNAPSHOT_STATES for s in sources)
    return {
        "snapshot_id": snapshot_id,
        "summary": counts,
        "stale_snapshot": stale,
        "sources": sources,
    }
