"""CLI integration tests for corpus, planning, and chamber hooks."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from adaptive_personal_syllabus.core import cli
from adaptive_personal_syllabus.storage import Storage


def _seed_dir(base: Path) -> Path:
    seed_dir = base / "seed"
    seed_dir.mkdir()
    (seed_dir / "taxonomy.json").write_text(
        json.dumps(
            {
                "nodes": [
                    {
                        "slug": "i-theoria",
                        "label": "Theoria",
                        "children": [
                            {"slug": "foundations", "label": "Foundations"},
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (seed_dir / "reading_lists.json").write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "title": "Intro to Theoria",
                        "organ_tags": ["i-theoria", "foundations"],
                        "difficulty": "beginner",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return seed_dir


def test_cli_corpus_ingest_stats_and_ledger_verify(tmp_path: Path) -> None:
    runner = CliRunner()
    db_path = tmp_path / "system.db"
    repo_root = Path(__file__).resolve().parents[1]

    ingest = runner.invoke(
        cli,
        [
            "corpus",
            "ingest",
            "--root",
            str(repo_root),
            "--snapshot",
            "repo-snap",
            "--db-path",
            str(db_path),
        ],
    )
    assert ingest.exit_code == 0
    ingest_data = json.loads(ingest.output)
    assert ingest_data["snapshot"]["snapshot_id"] > 0
    assert ingest_data["snapshot"]["doc_count"] > 0

    stats = runner.invoke(
        cli,
        [
            "corpus",
            "stats",
            "--snapshot-name",
            "repo-snap",
            "--db-path",
            str(db_path),
        ],
    )
    assert stats.exit_code == 0
    stats_data = json.loads(stats.output)
    assert stats_data["schema_version"] == "1.0"
    assert stats_data["snapshot"]["snapshot_name"] == "repo-snap"
    assert stats_data["document_count"] > 0

    verify = runner.invoke(cli, ["ledger", "verify", "--db-path", str(db_path)])
    assert verify.exit_code == 0
    verify_data = json.loads(verify.output)
    assert verify_data["ok"] is True


def test_cli_profile_init_and_plan_generate_json(tmp_path: Path) -> None:
    runner = CliRunner()
    db_path = tmp_path / "plan.db"
    profile_path = tmp_path / "profile.json"
    seed_dir = _seed_dir(tmp_path)

    init = runner.invoke(
        cli,
        [
            "profile",
            "init",
            "--name",
            "CLI Learner",
            "--organs",
            "I",
            "--level",
            "beginner",
            "--goals",
            "Build recursive curriculum",
            "--context",
            '{"industry":"education"}',
            "--output",
            str(profile_path),
            "--db-path",
            str(db_path),
        ],
    )
    assert init.exit_code == 0

    ingest_root = tmp_path / "corpus"
    ingest_root.mkdir()
    (ingest_root / "source.md").write_text("# Context\nBody", encoding="utf-8")

    ingest = runner.invoke(
        cli,
        [
            "corpus",
            "ingest",
            "--root",
            str(ingest_root),
            "--snapshot",
            "local",
            "--db-path",
            str(db_path),
        ],
    )
    assert ingest.exit_code == 0

    plan = runner.invoke(
        cli,
        [
            "plan",
            "generate",
            "--profile",
            str(profile_path),
            "--format",
            "json",
            "--seed-dir",
            str(seed_dir),
            "--db-path",
            str(db_path),
        ],
    )
    assert plan.exit_code == 0

    plan_data = json.loads(plan.output)
    assert plan_data["schema_version"] == "2.0"
    assert "plan_id" in plan_data
    assert "determinism_inputs" in plan_data
    assert plan_data["determinism_inputs"]["snapshot_id"] == plan_data["snapshot"]["id"]
    assert "modules" in plan_data
    assert plan_data["modules"]
    assert sorted(m["seq"] for m in plan_data["modules"]) == [
        m["seq"] for m in plan_data["modules"]
    ]


def test_cli_chamber_run_persists_hook_and_ledger(tmp_path: Path) -> None:
    runner = CliRunner()
    db_path = tmp_path / "hooks.db"

    result = runner.invoke(
        cli,
        [
            "chamber",
            "run",
            "--hook",
            "input_ritual",
            "--context",
            '{"request":"test"}',
            "--db-path",
            str(db_path),
        ],
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "ok"

    storage = Storage(db_path)
    with storage.connection() as conn:
        hook_runs = conn.execute("SELECT COUNT(*) AS n FROM hook_runs").fetchone()["n"]
        hook_events = conn.execute(
            "SELECT COUNT(*) AS n FROM ledger_events WHERE event_type = 'hook.execute'"
        ).fetchone()["n"]

    assert hook_runs == 1
    assert hook_events == 1


def test_cli_corpus_stats_can_select_snapshot_by_id(tmp_path: Path) -> None:
    runner = CliRunner()
    db_path = tmp_path / "system.db"

    root_one = tmp_path / "one"
    root_one.mkdir()
    (root_one / "a.md").write_text("# One\nA", encoding="utf-8")
    ingest_one = runner.invoke(
        cli,
        [
            "corpus",
            "ingest",
            "--root",
            str(root_one),
            "--snapshot",
            "one",
            "--db-path",
            str(db_path),
        ],
    )
    assert ingest_one.exit_code == 0
    snap_one_id = json.loads(ingest_one.output)["snapshot"]["snapshot_id"]

    root_two = tmp_path / "two"
    root_two.mkdir()
    (root_two / "b.md").write_text("# Two\nB", encoding="utf-8")
    (root_two / "c.md").write_text("# Two\nC", encoding="utf-8")
    ingest_two = runner.invoke(
        cli,
        [
            "corpus",
            "ingest",
            "--root",
            str(root_two),
            "--snapshot",
            "two",
            "--db-path",
            str(db_path),
        ],
    )
    assert ingest_two.exit_code == 0

    stats = runner.invoke(
        cli,
        ["corpus", "stats", "--snapshot-id", str(snap_one_id), "--db-path", str(db_path)],
    )
    assert stats.exit_code == 0
    stats_data = json.loads(stats.output)
    assert stats_data["snapshot"]["id"] == snap_one_id
    assert stats_data["snapshot"]["snapshot_name"] == "one"
    assert stats_data["document_count"] == 1
