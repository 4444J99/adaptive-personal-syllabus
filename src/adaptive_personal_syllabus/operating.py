"""Operating evidence — backup, restore, deletion, status, redaction.

#58 (MTR-027), ADR 012. The local offer only: the store is one SQLite
file on the operator's own machine, there is no hosted service, and the
operating evidence is the backup receipt, the restore drill, the deletion
receipt, the redacted diagnostic output, and the status check — all of it
checkable from the CLI on synthetic data, with no credentials and no
private service involved.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .ledger import Ledger
from .storage import DEFAULT_MAX_AGE_HOURS, Storage, utcnow_iso

# ADR 012, Decision 1-4: the operating budget and bounds for the local offer.
# These constants are the CLI's working copy of docs/operating-budget.yaml;
# tests/test_operating_readiness.py asserts the two agree, so a drift between
# the record and the code fails the suite instead of failing silently.
BUDGET_USD_PER_MONTH = 0
MAX_BACKUP_AGE_HOURS = 168  # one week; the budget artifact states the same bound
OPERATING_OWNER = "Anthony James Padavano (4444J99)"
ALERT_CHANNEL = "local-only: `syllabus ops status` non-zero exit plus a ledger receipt"
REDACTED = "[redacted]"

# Ledger event types this module appends. The payloads carry counts and
# hashes only — never a profile name, goals, or context object, so a
# deletion receipt cannot re-persist the personal data it deletes.
BACKUP_EVENT_TYPE = "ops.backup"
RESTORE_EVENT_TYPE = "ops.restore"
DELETE_PROFILE_EVENT_TYPE = "ops.delete-profile"


class OperatingError(ValueError):
    """An operating step refused: the store, backup, or budget is not as expected."""


def sha256_file(path: Path) -> str:
    """SHA-256 hex digest of a file's bytes."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_operating_budget(path: Path) -> dict[str, Any]:
    """Read and validate the operating-budget artifact (ADR 012).

    The artifact is the reviewable record; the CLI's built-in constants are
    its working copy. A file missing a required key is a refusal, not a
    default — a bound that can drift silently is not a bound.
    """
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise OperatingError(f"operating budget {path} is not a YAML mapping")
    for key in (
        "budget_usd_per_month",
        "max_backup_age_hours",
        "operating_owner",
        "alert_channel",
        "degradation_trigger",
    ):
        if key not in raw:
            raise OperatingError(f"operating budget {path} is missing {key!r}")
    return raw


def budget_record() -> dict[str, Any]:
    """The ADR 012 budget as the CLI reports it (mirrors the yaml artifact)."""
    return {
        "budget_usd_per_month": BUDGET_USD_PER_MONTH,
        "max_backup_age_hours": MAX_BACKUP_AGE_HOURS,
        "operating_owner": OPERATING_OWNER,
        "alert_channel": ALERT_CHANNEL,
        "degradation_trigger": (
            "any ops status check failing: pause new ingestion/generation until green; "
            "rollback is `syllabus ops restore` from the last verified backup"
        ),
        "uptime_promise": None,
    }


def open_store(db_path: Path) -> Storage:
    """Open a store, refusing cleanly when SQLite cannot read it at all.

    Used by the `ops` commands that must report a failure, not crash, on
    a corrupt store — `ops status` especially, since it is the alert path.
    """
    try:
        return Storage(db_path)
    except sqlite3.Error as exc:
        raise OperatingError(f"store at {db_path} failed to open: {exc}") from exc


def backup_store(db_path: Path, output_path: Path) -> dict[str, Any]:
    """Copy the live store to a named location with a checksum receipt.

    Uses the SQLite backup API, not a raw file copy: a copy taken while a
    writer holds the database can be torn, and a torn backup is worse than
    no backup because it looks like evidence. The receipt is appended to the
    live ledger (the backup file itself stays a faithful copy of the store
    at backup time, so it does not contain its own receipt event).
    """
    db_path = Path(db_path).expanduser().resolve()
    output_path = Path(output_path).expanduser().resolve()
    if not db_path.is_file():
        raise OperatingError(f"no store at {db_path}")
    if output_path == db_path:
        raise OperatingError("backup output must not be the live store itself")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    storage = open_store(db_path)
    source_head = storage.last_ledger_hash()
    source_events = storage.ledger_event_count()

    tmp_fd, tmp_name = tempfile.mkstemp(
        dir=str(output_path.parent), prefix=output_path.name + ".", suffix=".tmp"
    )
    os.close(tmp_fd)
    tmp_path = Path(tmp_name)
    try:
        source = sqlite3.connect(db_path)
        try:
            target = sqlite3.connect(tmp_path)
            try:
                source.backup(target)
            finally:
                target.close()
        finally:
            source.close()
        digest = sha256_file(tmp_path)
        size = tmp_path.stat().st_size
        os.replace(tmp_path, output_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

    Ledger(storage).append(
        BACKUP_EVENT_TYPE,
        {
            "backup_path": str(output_path),
            "sha256": digest,
            "bytes": size,
            "source_head_hash": source_head,
            "source_event_count": source_events,
        },
    )
    return {
        "operation": "backup",
        "db_path": str(db_path),
        "backup_path": str(output_path),
        "sha256": digest,
        "bytes": size,
        "source_head_hash": source_head,
        "source_event_count": source_events,
        "created_at": utcnow_iso(),
    }


def _verify_store_at(path: Path) -> tuple[bool, list[str], int]:
    """Integrity + ledger verification for a store file (read-only intent).

    Opens the file through Storage (migrations run on the opened copy only
    when the caller passes a temp copy) and reports the same verdict the
    `ledger verify` command prints. A file SQLite cannot open at all is a
    failed verification, not an exception: a corrupt backup must be
    refused cleanly.
    """
    try:
        storage = Storage(path)
        integrity = storage.integrity_check()
        chain = Ledger(storage)
        ok, errors, event_count = chain.verify_chain()
    except sqlite3.Error as exc:
        return False, [f"error: {exc}"], 0
    if integrity != ["ok"]:
        errors = [f"integrity: {line}" for line in integrity] + errors
        ok = False
    return ok, errors, event_count


def restore_store(backup_path: Path, db_path: Path) -> dict[str, Any]:
    """Rebuild the live store from a backup and verify it afterwards.

    Refuses a backup that fails integrity or ledger verification, and
    refuses to swap while the live store cannot be read for its previous
    head hash. The swap itself is atomic (`os.replace`); the restored
    chain is verified on the live path before the restore receipt is
    appended, so the receipt never launders a bad restore.
    """
    backup_path = Path(backup_path).expanduser().resolve()
    db_path = Path(db_path).expanduser().resolve()
    if not backup_path.is_file():
        raise OperatingError(f"no backup at {backup_path}")
    digest = sha256_file(backup_path)

    with tempfile.TemporaryDirectory(prefix="ops-restore-") as tmpdir:
        probe = Path(tmpdir) / "probe.db"
        probe.write_bytes(backup_path.read_bytes())
        ok, errors, backup_events = _verify_store_at(probe)
        if not ok:
            raise OperatingError(
                "backup failed verification and was not restored: " + "; ".join(errors)
            )

    previous_head = ""
    if db_path.is_file():
        # A corrupt live store is exactly when restore is most needed, so
        # an unreadable head is recorded, not a refusal.
        try:
            previous_head = open_store(db_path).last_ledger_hash()
        except OperatingError:
            previous_head = "<unreadable>"

    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_name = tempfile.mkstemp(
        dir=str(db_path.parent), prefix=db_path.name + ".", suffix=".tmp"
    )
    os.close(tmp_fd)
    tmp_path = Path(tmp_name)
    try:
        tmp_path.write_bytes(backup_path.read_bytes())
        os.replace(tmp_path, db_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
    for suffix in ("-wal", "-shm", "-journal"):
        sibling = Path(str(db_path) + suffix)
        if sibling.exists():
            sibling.unlink()

    storage = open_store(db_path)
    ok, errors, restored_events = _verify_store_at(db_path)
    if not ok:
        raise OperatingError(
            "restored store failed verification on the live path: " + "; ".join(errors)
        )
    Ledger(storage).append(
        RESTORE_EVENT_TYPE,
        {
            "backup_path": str(backup_path),
            "backup_sha256": digest,
            "previous_head_hash": previous_head,
            "restored_event_count": restored_events,
        },
    )
    return {
        "operation": "restore",
        "db_path": str(db_path),
        "backup_path": str(backup_path),
        "backup_sha256": digest,
        "previous_head_hash": previous_head,
        "restored_event_count": restored_events,
        "backup_event_count": backup_events,
        "created_at": utcnow_iso(),
    }


def delete_learner(storage: Storage, profile_id: int) -> dict[str, Any]:
    """Delete one learner profile and its dependent plans, with a receipt.

    The receipt carries counts only — no name, goals, or context — so the
    deletion cannot re-persist the personal data it deletes. The
    `profile.init` ledger event for the profile stays: the ledger is
    append-only (#52), and the receipt explains the deletion instead of
    rewriting history.
    """
    counts = storage.delete_profile(profile_id)
    if counts["profiles_deleted"] == 0:
        raise OperatingError(f"no profile with id {profile_id}")
    Ledger(storage).append(
        DELETE_PROFILE_EVENT_TYPE,
        {
            "profile_id": profile_id,
            "profiles_deleted": counts["profiles_deleted"],
            "plans_deleted": counts["plans_deleted"],
        },
    )
    return {
        "operation": "delete-profile",
        "profile_id": profile_id,
        "profiles_deleted": counts["profiles_deleted"],
        "plans_deleted": counts["plans_deleted"],
        "created_at": utcnow_iso(),
    }


def redact_plan_doc(doc: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of a plan doc with learner content redacted.

    Name, goals, and context are identifying; level and organs are not.
    The redaction is applied to the output copy only — the stored plan is
    untouched, so a redacted view can never destroy the record it hides.
    """
    redacted = copy.deepcopy(doc)
    profile = redacted.get("profile")
    if isinstance(profile, dict):
        if "name" in profile:
            profile["name"] = REDACTED
        if "goals" in profile:
            profile["goals"] = []
        if "context" in profile:
            profile["context"] = {}
    return redacted


def _parse_created_at(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def latest_backup_receipt(storage: Storage) -> dict[str, Any] | None:
    """The newest `ops.backup` ledger event, or None when no backup exists."""
    for event in reversed(storage.iter_ledger_events()):
        if event.get("event_type") == BACKUP_EVENT_TYPE:
            payload = json.loads(str(event["payload_json"]))
            return {
                "created_at": str(event["created_at"]),
                "backup_path": str(payload.get("backup_path", "")),
                "sha256": str(payload.get("sha256", "")),
                "bytes": int(payload.get("bytes", 0)),
            }
    return None


def latest_recovery_event(storage: Storage) -> dict[str, Any] | None:
    """The newest backup or restore receipt, for the status detail only.

    A restore does not satisfy the backup bound — the restored store has
    no backup receipt until the operator backs it up again — but when
    the latest recovery evidence is a restore, the status detail should
    say so instead of claiming no backup ever existed.
    """
    for event in reversed(storage.iter_ledger_events()):
        if event.get("event_type") in (BACKUP_EVENT_TYPE, RESTORE_EVENT_TYPE):
            return {
                "event_type": str(event["event_type"]),
                "created_at": str(event["created_at"]),
            }
    return None


def stale_sources(storage: Storage) -> list[dict[str, Any]]:
    """Sources whose last good retrieval is older than their max age (#54).

    A source with no content version yet has nothing to be stale about;
    a source whose max age is unset uses the #54 default bound.
    """
    now = datetime.now(tz=UTC)
    stale: list[dict[str, Any]] = []
    for record in storage.list_source_records():
        latest = storage.latest_content_version(int(record["id"]))
        if latest is None:
            continue
        retrieved = _parse_created_at(str(latest["retrieved_at"]))
        if retrieved is None:
            continue
        max_age = int(record.get("max_age_hours") or DEFAULT_MAX_AGE_HOURS)
        age_hours = (now - retrieved).total_seconds() / 3600
        if age_hours > max_age:
            stale.append(
                {
                    "root_path": str(record["root_path"]),
                    "rel_path": str(record["rel_path"]),
                    "age_hours": round(age_hours, 1),
                    "max_age_hours": max_age,
                    "last_outcome": str(latest["outcome"]),
                }
            )
    return stale


def operating_status(storage: Storage, *, budget_path: Path | None = None) -> dict[str, Any]:
    """Evaluate every operating check and report the verdict (ADR 012).

    Checks: store integrity, ledger chain, backup freshness (a backup
    receipt within MAX_BACKUP_AGE_HOURS), source freshness (#54), and the
    budget read-back. Overall `ok` is false when any check fails; a
    missing or stale backup fails the run — a store with no verified
    backup has no recovery evidence, and the status command is where that
    shows up instead of staying silent.
    """
    budget = (
        load_operating_budget(budget_path)
        if budget_path is not None
        else budget_record()
    )
    checks: list[dict[str, Any]] = []

    integrity = storage.integrity_check()
    checks.append(
        {
            "name": "store_integrity",
            "status": "ok" if integrity == ["ok"] else "fail",
            "detail": "ok" if integrity == ["ok"] else "; ".join(integrity),
        }
    )

    chain = Ledger(storage)
    ok, errors, event_count = chain.verify_chain()
    checks.append(
        {
            "name": "ledger",
            "status": "ok" if ok else "fail",
            "detail": f"{event_count} events, chain valid"
            if ok
            else "; ".join(errors),
        }
    )

    receipt = latest_backup_receipt(storage)
    max_age = int(budget.get("max_backup_age_hours", MAX_BACKUP_AGE_HOURS))
    if receipt is None:
        recovery = latest_recovery_event(storage)
        if recovery is not None and recovery["event_type"] == RESTORE_EVENT_TYPE:
            detail = (
                "no backup receipt in the ledger "
                f"(last recovery evidence: restore at {recovery['created_at']}); "
                "run `syllabus ops backup` to establish a backup of the restored store"
            )
        else:
            detail = "no backup receipt in the ledger; run `syllabus ops backup`"
        checks.append({"name": "backup_fresh", "status": "fail", "detail": detail})
    else:
        created = _parse_created_at(receipt["created_at"])
        age_hours = (
            (datetime.now(tz=UTC) - created).total_seconds() / 3600
            if created is not None
            else float("inf")
        )
        checks.append(
            {
                "name": "backup_fresh",
                "status": "ok" if age_hours <= max_age else "fail",
                "detail": (
                    f"last backup {receipt['created_at']} "
                    f"({age_hours:.1f}h ago, bound {max_age}h, "
                    f"sha256 {receipt['sha256'][:12]}…)"
                ),
            }
        )

    stale = stale_sources(storage)
    checks.append(
        {
            "name": "source_freshness",
            "status": "ok" if not stale else "fail",
            "detail": "no stale sources"
            if not stale
            else f"{len(stale)} stale source(s): "
            + ", ".join(f"{s['rel_path']} ({s['age_hours']}h)" for s in stale),
        }
    )

    checks.append(
        {
            "name": "budget",
            "status": "ok",
            "detail": (
                f"${budget.get('budget_usd_per_month')} / month marginal; "
                f"owner {budget.get('operating_owner')}; "
                f"alert channel: {budget.get('alert_channel')}"
            ),
        }
    )

    return {
        "schema_version": "1.0",
        "ok": all(check["status"] == "ok" for check in checks),
        "checks": checks,
        "budget": {
            "budget_usd_per_month": budget.get("budget_usd_per_month"),
            "max_backup_age_hours": max_age,
            "operating_owner": budget.get("operating_owner"),
            "alert_channel": budget.get("alert_channel"),
            "degradation_trigger": budget.get("degradation_trigger"),
            "uptime_promise": budget.get("uptime_promise"),
        },
        "generated_at": utcnow_iso(),
    }
