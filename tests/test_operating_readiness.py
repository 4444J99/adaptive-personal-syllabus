"""Operating-readiness drills (#58, MTR-027, ADR 012).

Every acceptance predicate in #58 is a drill that runs in CI on synthetic
data: backup writes a verifiable copy, restore rebuilds the store and
passes integrity + ledger verification (and refuses a corrupt backup),
deletion removes the record with a receipt that carries no personal data,
diagnostic output redacts the learner, and the budget artifact reads back
the ADR 012 decision. Nothing here touches a real learner record.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

import yaml
from click.testing import CliRunner

from adaptive_personal_syllabus.core import cli
from adaptive_personal_syllabus.operating import budget_record
from adaptive_personal_syllabus.storage import Storage

REPO_ROOT = Path(__file__).resolve().parents[1]
SEED_DIR = REPO_ROOT / "tests" / "fixtures" / "seed"

NAME = "Synthetic Learner"
GOALS = "synthetic-goal-alpha,synthetic-goal-beta"
CONTEXT = '{"note": "synthetic-context-beta"}'
TOKENS = (NAME, "synthetic-goal-alpha", "synthetic-context-beta")


def _profile_ids(db_path: Path) -> list[int]:
    conn = sqlite3.connect(db_path)
    try:
        return [int(r[0]) for r in conn.execute("SELECT id FROM profiles").fetchall()]
    finally:
        conn.close()


def _plan_ids(db_path: Path) -> list[int]:
    conn = sqlite3.connect(db_path)
    try:
        return [int(r[0]) for r in conn.execute("SELECT id FROM plans").fetchall()]
    finally:
        conn.close()


def _setup_store(runner: CliRunner, tmp_path: Path, stem: str = "store") -> tuple[Path, int]:
    """Build a synthetic store with one profile and one generated plan."""
    db_path = tmp_path / f"{stem}.db"
    profile_path = tmp_path / f"{stem}-profile.json"
    result = runner.invoke(
        cli,
        [
            "profile", "init",
            "--name", NAME,
            "--goals", GOALS,
            "--context", CONTEXT,
            "--db-path", str(db_path),
            "--output", str(profile_path),
        ],
    )
    assert result.exit_code == 0, result.output
    result = runner.invoke(
        cli,
        ["corpus", "ingest", "--root", str(SEED_DIR),
         "--snapshot", "drill-synthetic", "--db-path", str(db_path)],
    )
    assert result.exit_code == 0, result.output
    result = runner.invoke(
        cli,
        ["plan", "generate", "--profile", str(profile_path),
         "--db-path", str(db_path), "--seed-dir", str(SEED_DIR), "--format", "json"],
    )
    assert result.exit_code == 0, result.output
    plan_doc = json.loads(result.output)
    return db_path, int(plan_doc["db_plan_id"])


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _payload(result) -> dict:
    """Parse a CLI JSON payload, ignoring a trailing Click error line.

    CliRunner mixes stderr into the output, so a failing invocation prints
    the JSON payload followed by `Error: ...`; the payload is everything
    before that line.
    """
    return json.loads(result.output.split("\nError:", 1)[0])


def test_backup_writes_verifiable_copy(tmp_path: Path) -> None:
    """A backup is a byte-faithful store copy whose checksum the receipt binds."""
    runner = CliRunner()
    db_path, _ = _setup_store(runner, tmp_path)
    backup_path = tmp_path / "backup.db"
    result = runner.invoke(
        cli, ["ops", "backup", "--db-path", str(db_path), "--output", str(backup_path)]
    )
    assert result.exit_code == 0, result.output
    receipt = json.loads(result.output)
    assert receipt["sha256"] == _sha256(backup_path)
    assert receipt["bytes"] == backup_path.stat().st_size
    assert receipt["source_event_count"] >= 2  # profile.init + plan.generate
    # The copy verifies as a store on its own (checked on a scratch copy so
    # the backup file itself stays byte-identical to the receipt).
    probe = tmp_path / "probe.db"
    shutil.copyfile(backup_path, probe)
    result = runner.invoke(cli, ["ledger", "verify", "--db-path", str(probe)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["ok"] is True


def test_restore_rebuilds_store_and_verifies(tmp_path: Path) -> None:
    """Restore after losing the store brings the plan back, verified live."""
    runner = CliRunner()
    db_path, plan_id = _setup_store(runner, tmp_path)
    backup_path = tmp_path / "backup.db"
    result = runner.invoke(
        cli, ["ops", "backup", "--db-path", str(db_path), "--output", str(backup_path)]
    )
    assert result.exit_code == 0, result.output
    db_path.unlink()
    assert not db_path.exists()
    result = runner.invoke(
        cli, ["ops", "restore", "--backup", str(backup_path), "--db-path", str(db_path)]
    )
    assert result.exit_code == 0, result.output
    receipt = json.loads(result.output)
    assert receipt["backup_sha256"] == _sha256(backup_path)
    assert receipt["restored_event_count"] >= 2
    result = runner.invoke(cli, ["ledger", "verify", "--db-path", str(db_path)])
    assert result.exit_code == 0, result.output
    result = runner.invoke(
        cli, ["plan", "show", str(plan_id), "--db-path", str(db_path), "--format", "json"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["db_plan_id"] == plan_id


def test_restore_refuses_corrupt_backup(tmp_path: Path) -> None:
    """A backup that fails verification is refused and the live store is untouched.

    The corruption is a tampered ledger payload: it deterministically
    breaks the hash chain (a byte flip at an arbitrary file offset is
    not deterministic — it can land in free space integrity_check does
    not examine).
    """
    runner = CliRunner()
    db_path, _ = _setup_store(runner, tmp_path)
    backup_path = tmp_path / "backup.db"
    result = runner.invoke(
        cli, ["ops", "backup", "--db-path", str(db_path), "--output", str(backup_path)]
    )
    assert result.exit_code == 0, result.output
    before = _sha256(db_path)
    conn = sqlite3.connect(backup_path)
    conn.execute("UPDATE ledger_events SET payload_json = '{\"tampered\": true}' WHERE id = 1")
    conn.commit()
    conn.close()
    result = runner.invoke(
        cli, ["ops", "restore", "--backup", str(backup_path), "--db-path", str(db_path)]
    )
    assert result.exit_code != 0
    assert "verification" in result.output
    assert _sha256(db_path) == before
    result = runner.invoke(cli, ["ledger", "verify", "--db-path", str(db_path)])
    assert result.exit_code == 0, result.output


def test_delete_profile_removes_record_and_plans(tmp_path: Path) -> None:
    """Deletion removes the profile, its plans, and its stored payloads."""
    runner = CliRunner()
    db_path, plan_id = _setup_store(runner, tmp_path)
    profile_ids = _profile_ids(db_path)
    assert len(profile_ids) == 1
    assert _plan_ids(db_path) == [plan_id]
    result = runner.invoke(
        cli,
        ["ops", "delete-profile", str(profile_ids[0]), "--db-path", str(db_path)],
    )
    assert result.exit_code == 0, result.output
    receipt = json.loads(result.output)
    assert receipt["profiles_deleted"] == 1
    assert receipt["plans_deleted"] == 1
    assert _profile_ids(db_path) == []
    assert _plan_ids(db_path) == []
    result = runner.invoke(
        cli, ["plan", "show", str(plan_id), "--db-path", str(db_path), "--format", "json"]
    )
    assert result.exit_code != 0
    result = runner.invoke(cli, ["ledger", "verify", "--db-path", str(db_path)])
    assert result.exit_code == 0, result.output


def test_delete_profile_receipt_carries_no_personal_data(tmp_path: Path) -> None:
    """The deletion receipt proves the deletion without re-persisting the data."""
    runner = CliRunner()
    db_path, _ = _setup_store(runner, tmp_path)
    profile_id = _profile_ids(db_path)[0]
    result = runner.invoke(
        cli, ["ops", "delete-profile", str(profile_id), "--db-path", str(db_path)]
    )
    assert result.exit_code == 0, result.output
    storage = Storage(db_path)
    receipts = [
        json.loads(str(e["payload_json"]))
        for e in storage.iter_ledger_events()
        if e["event_type"] == "ops.delete-profile"
    ]
    assert len(receipts) == 1
    blob = json.dumps(receipts[0])
    assert all(token not in blob for token in TOKENS)


def test_restore_does_not_satisfy_backup_bound(tmp_path: Path) -> None:
    """A restore proves the backup, not a backup of the restored store.

    The restored store carries an `ops.restore` receipt but no backup
    receipt, so status fails backup_fresh until the operator backs the
    restored store up again (ADR 012, Decision 4). The detail must name
    the restore instead of claiming no backup ever existed.
    """
    runner = CliRunner()
    db_path, _ = _setup_store(runner, tmp_path)
    backup_path = tmp_path / "backup.db"
    result = runner.invoke(
        cli, ["ops", "backup", "--db-path", str(db_path), "--output", str(backup_path)]
    )
    assert result.exit_code == 0, result.output
    db_path.unlink()
    result = runner.invoke(
        cli, ["ops", "restore", "--backup", str(backup_path), "--db-path", str(db_path)]
    )
    assert result.exit_code == 0, result.output
    result = runner.invoke(cli, ["ops", "status", "--db-path", str(db_path)])
    assert result.exit_code != 0
    payload = _payload(result)
    assert payload["ok"] is False
    fresh = next(c for c in payload["checks"] if c["name"] == "backup_fresh")
    assert fresh["status"] == "fail"
    assert "restore at" in fresh["detail"]
    result = runner.invoke(
        cli, ["ops", "backup", "--db-path", str(db_path),
         "--output", str(tmp_path / "backup2.db")]
    )
    assert result.exit_code == 0, result.output
    result = runner.invoke(cli, ["ops", "status", "--db-path", str(db_path)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["ok"] is True


def test_delete_profile_refuses_unknown_id(tmp_path: Path) -> None:
    """Deleting a profile that does not exist fails loudly instead of no-op."""
    runner = CliRunner()
    db_path, _ = _setup_store(runner, tmp_path)
    result = runner.invoke(
        cli, ["ops", "delete-profile", "999", "--db-path", str(db_path)]
    )
    assert result.exit_code != 0
    assert "no profile with id 999" in result.output


def test_redacted_plan_show_contains_no_profile_tokens(tmp_path: Path) -> None:
    """Redacted plan output carries no name, goals, or context, in any format."""
    runner = CliRunner()
    db_path, plan_id = _setup_store(runner, tmp_path)
    for fmt in ("json", "md", "text"):
        plain = runner.invoke(
            cli,
            ["plan", "show", str(plan_id), "--db-path", str(db_path), "--format", fmt],
        )
        assert plain.exit_code == 0, plain.output
        redacted = runner.invoke(
            cli,
            ["plan", "show", str(plan_id), "--db-path", str(db_path),
             "--format", fmt, "--redacted"],
        )
        assert redacted.exit_code == 0, redacted.output
        assert all(token not in redacted.output for token in TOKENS), fmt
        assert "[redacted]" in redacted.output or fmt == "text"
    # The unredacted surface is what the redaction removes: json and md
    # carry the name (step 1 reproduction), so the flag has work to do.
    plain_json = runner.invoke(
        cli, ["plan", "show", str(plan_id), "--db-path", str(db_path), "--format", "json"]
    )
    assert NAME in plain_json.output


def test_redacted_plan_generate_contains_no_profile_tokens(tmp_path: Path) -> None:
    """Redacted generation output carries no profile tokens either."""
    runner = CliRunner()
    db_path, _ = _setup_store(runner, tmp_path)
    profile_path = tmp_path / "store-profile.json"
    result = runner.invoke(
        cli,
        ["plan", "generate", "--profile", str(profile_path),
         "--db-path", str(db_path), "--seed-dir", str(SEED_DIR),
         "--format", "json", "--redacted"],
    )
    assert result.exit_code == 0, result.output
    assert all(token not in result.output for token in TOKENS)


def test_budget_artifact_reads_back_adr012_decision() -> None:
    """The yaml artifact and the CLI's working copy agree on the decision."""
    artifact = yaml.safe_load(
        (REPO_ROOT / "docs" / "operating-budget.yaml").read_text(encoding="utf-8")
    )
    assert artifact["budget_usd_per_month"] == 0
    assert artifact["max_backup_age_hours"] == 168
    assert "Anthony James Padavano" in str(artifact["operating_owner"])
    assert "restore" in str(artifact["degradation_trigger"])
    assert artifact["uptime_promise"] is None
    record = budget_record()
    assert record["budget_usd_per_month"] == artifact["budget_usd_per_month"]
    assert record["max_backup_age_hours"] == artifact["max_backup_age_hours"]
    assert record["operating_owner"] == artifact["operating_owner"]
    assert record["alert_channel"] == artifact["alert_channel"]


def test_status_ok_after_backup_and_fails_on_corrupt_store(tmp_path: Path) -> None:
    """Status fails with no backup evidence, passes after one, fails on corruption.

    The corruption is a truncated store file: it deterministically fails
    to open, which exercises the status command's failing-payload path
    (an unreadable store is the alert firing, not a reason to stay
    silent). A byte flip at an arbitrary offset is not deterministic —
    it can land in free space.
    """
    runner = CliRunner()
    db_path, _ = _setup_store(runner, tmp_path)
    result = runner.invoke(cli, ["ops", "status", "--db-path", str(db_path)])
    assert result.exit_code != 0
    payload = _payload(result)
    assert payload["ok"] is False
    assert any(
        c["name"] == "backup_fresh" and c["status"] == "fail" for c in payload["checks"]
    )
    backup_path = tmp_path / "backup.db"
    result = runner.invoke(
        cli, ["ops", "backup", "--db-path", str(db_path), "--output", str(backup_path)]
    )
    assert result.exit_code == 0, result.output
    result = runner.invoke(cli, ["ops", "status", "--db-path", str(db_path)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert all(c["status"] == "ok" for c in payload["checks"])
    assert payload["budget"]["budget_usd_per_month"] == 0
    data = db_path.read_bytes()
    db_path.write_bytes(data[: len(data) // 2])
    result = runner.invoke(cli, ["ops", "status", "--db-path", str(db_path)])
    assert result.exit_code != 0
    assert _payload(result)["ok"] is False


def test_adr_012_records_the_decision() -> None:
    """ADR 012 names the local offer, the owner, the $0 budget, and no uptime promise."""
    text = (REPO_ROOT / "docs" / "adr" / "012-operating-evidence.md").read_text(
        encoding="utf-8"
    )
    assert "local offer" in text
    assert "Anthony James Padavano" in text
    assert "$0" in text
    assert "No uptime promise" in text
    assert "168" in text


def test_runbooks_name_owner_command_and_failure() -> None:
    """Each runbook names its owner, its command, and what failure looks like."""
    for name in ("backup", "restore", "deletion", "alert"):
        text = (REPO_ROOT / "runbooks" / f"{name}.md").read_text(encoding="utf-8")
        assert "Owner" in text, name
        assert "syllabus ops" in text, name
        assert "fail" in text.lower(), name
