"""Compatibility-promise tests (ADR 008, #53).

Pins the single authoritative version, the emitted schema versions, the
0.5.0-era plan fixture, and the SQLite schema marker — so the next drift
fails CI instead of shipping.
"""

from __future__ import annotations

import json
import re
import sqlite3
import tomllib
from pathlib import Path

from click.testing import CliRunner

from adaptive_personal_syllabus import _FALLBACK_VERSION, __version__
from adaptive_personal_syllabus.core import (
    _render_plan_markdown,
    _render_plan_text,
    cli,
)
from adaptive_personal_syllabus.storage import Storage
from adaptive_personal_syllabus.versions import (
    AUDIT_REPORT_SCHEMA_VERSION,
    CLI_ENVELOPE_SCHEMA_VERSION,
    DB_SCHEMA_VERSION,
    ENCOUNTER_SCHEMA_VERSION,
    LEGACY_PROJECTION_SCHEMA_VERSION,
    MILESTONE_EXECUTION_PLAN_SCHEMA_VERSION,
    PLAN_SCHEMA_VERSION,
    PROFILE_SCHEMA_VERSION,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _pyproject_version() -> str:
    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        return str(tomllib.load(fh)["project"]["version"])


def _changelog_released_versions() -> list[str]:
    text = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    return re.findall(r"^## \[(\d+\.\d+\.\d+)\] - ", text, flags=re.MULTILINE)


def test_version_is_single_sourced() -> None:
    """`syllabus version` == `__version__` == pyproject == latest release."""
    version = _pyproject_version()
    assert __version__ == version
    assert _FALLBACK_VERSION == version
    runner = CliRunner()
    result = runner.invoke(cli, ["version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"adaptive-personal-syllabus v{version}"
    released = _changelog_released_versions()
    assert released, "CHANGELOG has no released version section"
    assert released[0] == version


def test_schema_version_constants_match_the_matrix() -> None:
    """The ADR 008 matrix values are pinned, not just documented."""
    assert PLAN_SCHEMA_VERSION == "2.0"
    assert CLI_ENVELOPE_SCHEMA_VERSION == "1.0"
    assert PROFILE_SCHEMA_VERSION == "1.0"
    assert ENCOUNTER_SCHEMA_VERSION == "1.2"
    assert MILESTONE_EXECUTION_PLAN_SCHEMA_VERSION == "1.0"
    assert AUDIT_REPORT_SCHEMA_VERSION == "2.0"
    assert LEGACY_PROJECTION_SCHEMA_VERSION == "legacy_projection"
    assert DB_SCHEMA_VERSION == 1


def _ingested_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "compat.db"
    corpus_root = tmp_path / "corpus"
    corpus_root.mkdir()
    (corpus_root / "doc.md").write_text("# Heading\nBody", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["corpus", "ingest", "--root", str(corpus_root),
         "--snapshot", "compat", "--db-path", str(db_path)],
    )
    assert result.exit_code == 0, result.output
    return db_path


def test_cli_envelopes_carry_the_envelope_version(tmp_path: Path) -> None:
    db_path = _ingested_db(tmp_path)
    runner = CliRunner()
    stats = runner.invoke(cli, ["corpus", "stats", "--db-path", str(db_path)])
    assert stats.exit_code == 0, stats.output
    assert json.loads(stats.output)["schema_version"] == "1.0"
    verify = runner.invoke(cli, ["ledger", "verify", "--db-path", str(db_path)])
    assert verify.exit_code == 0, verify.output
    assert json.loads(verify.output)["schema_version"] == "1.0"


def test_generated_plan_carries_plan_schema_version(tmp_path: Path) -> None:
    db_path = _ingested_db(tmp_path)
    profile_path = tmp_path / "profile.json"
    runner = CliRunner()
    init = runner.invoke(
        cli,
        ["profile", "init", "--name", "Compat", "--organs", "I",
         "--purpose", "evaluate", "--phone-only",
         "--output", str(profile_path), "--db-path", str(db_path)],
    )
    assert init.exit_code == 0, init.output
    generated = runner.invoke(
        cli,
        ["plan", "generate", "--profile", str(profile_path),
         "--seed-dir", str(REPO_ROOT / "tests" / "fixtures" / "seed"),
         "--format", "json", "--db-path", str(db_path)],
    )
    assert generated.exit_code == 0, generated.output
    plan = json.loads(generated.output)
    assert plan["schema_version"] == "2.0"
    assert plan["determinism_inputs"]["fingerprint_schema_version"] == 2
    assert plan["modules"][0]["source_selection"]["schema_version"] == 1


def test_050_era_plan_still_reads_and_renders() -> None:
    """A 0.5.0-era plan JSON (schema 1.0) still parses and renders (ADR 008).

    The fixture mirrors the plan dict the 0.5.0-era planner built
    (commit 9e1706d9, planner.py lines 199-232): same fields, synthetic
    values. Readers must not reject an older schema version they
    understand — `plan show` renders it through the same code path as a
    current plan.
    """
    fixture = json.loads(
        (REPO_ROOT / "tests" / "fixtures" / "plan-0.5.0-era.json").read_text(
            encoding="utf-8"
        )
    )
    assert fixture["schema_version"] == "1.0"
    assert fixture["plan_id"] == "plan-0.5.0-era-fixture"
    text = _render_plan_text(fixture)
    assert "Fixture Foundations" in text
    assert "plan-0.5.0-era-fixture" in text
    markdown = _render_plan_markdown(fixture)
    assert "# Learning Path: I" in markdown
    assert json.loads(json.dumps(fixture)) == fixture


def test_db_marker_stamped_on_fresh_database(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "fresh.db")
    assert storage.schema_version() == 1


def test_pre_marker_database_gains_marker_with_data_intact(tmp_path: Path) -> None:
    """A database created before the marker opens, stamps 1, keeps data."""
    db_path = tmp_path / "legacy.db"
    storage = Storage(db_path)
    snapshot_id = storage.insert_snapshot("legacy", "/synthetic", 1, 1)
    assert storage.schema_version() == 1
    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP TABLE schema_meta")
        conn.commit()
    reopened = Storage(db_path)
    assert reopened.schema_version() == 1
    assert reopened.latest_snapshot()["id"] == snapshot_id


def test_newer_marker_database_refuses_to_open(tmp_path: Path) -> None:
    db_path = tmp_path / "newer.db"
    Storage(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE schema_meta SET value = '99' WHERE key = 'schema_version'")
        conn.commit()
    try:
        Storage(db_path)
    except ValueError as exc:
        assert "newer" in str(exc) and "99" in str(exc)
    else:
        raise AssertionError("expected ValueError for a newer schema marker")
