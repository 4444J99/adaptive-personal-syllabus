"""Tests for live-source refresh (#54, MTR-018).

Fixtures are synthetic local corpora only — a local directory stands in
for the remote source, clearly labeled. No real remote, no private data.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from click.testing import CliRunner

import adaptive_personal_syllabus.corpus as corpus_module
from adaptive_personal_syllabus.core import cli
from adaptive_personal_syllabus.corpus import (
    CorpusIngestor,
    CorpusRefresher,
    RateLimitError,
)
from adaptive_personal_syllabus.freshness import source_freshness
from adaptive_personal_syllabus.ledger import Ledger
from adaptive_personal_syllabus.planner import Planner
from adaptive_personal_syllabus.storage import Storage
from tests.admission_helpers import admit_all_documents


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
                            {"slug": "abstractions", "label": "Abstractions"},
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


def _profile(path: Path) -> Path:
    profile_path = path / "profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "name": "Refresh Test",
                "organs_of_interest": ["I"],
                "level": "beginner",
                "goals": ["Build a recursive system"],
                "context": {"industry": "education"},
                "completed_modules": [],
                "output_policy": {"selected_wings": []},
            }
        ),
        encoding="utf-8",
    )
    return profile_path


def _setup(tmp_path: Path, files: dict[str, str]):
    """A synthetic corpus + storage + ledger; returns (root, storage, ledger)."""
    root = tmp_path / "corpus"
    root.mkdir()
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    storage = Storage(tmp_path / "test.db")
    ledger = Ledger(storage)
    return root, storage, ledger


def _ingest(root: Path, storage: Storage, ledger: Ledger, name: str = "snap-1"):
    return CorpusIngestor(storage, ledger).ingest(root, name)


def _refresh(root: Path, storage: Storage, ledger: Ledger, **kwargs):
    return CorpusRefresher(storage, ledger).refresh(root, **kwargs)


def _version_rows(storage: Storage, rel_path: str, root: str) -> list[dict]:
    record = storage.find_source_record(root, rel_path)
    assert record is not None
    with storage.connection() as conn:
        rows = conn.execute(
            "SELECT * FROM source_versions WHERE source_id = ? ORDER BY id",
            (int(record["id"]),),
        ).fetchall()
    return [dict(row) for row in rows]


def _candidates(plan: dict) -> list[dict]:
    return [
        candidate
        for module in plan["modules"]
        for candidate in module["source_selection"]["candidates"]
    ]


def test_refresh_records_first_observation(tmp_path: Path) -> None:
    root, storage, ledger = _setup(tmp_path, {"a.md": "# A\nalpha"})
    _ingest(root, storage, ledger)
    summary = _refresh(root, storage, ledger)

    assert summary["outcome_counts"] == {"ok": 1}
    assert summary["refresh_run_id"] > 0
    record = storage.find_source_record(str(root), "a.md")
    assert record is not None
    assert int(record["max_age_hours"]) == 168
    rows = _version_rows(storage, "a.md", str(root))
    assert len(rows) == 1
    assert rows[0]["outcome"] == "ok"
    assert rows[0]["sha256"]
    assert rows[0]["retrieved_at"]
    assert rows[0]["source_version"] == str(summary["refresh_run_id"])

    # The ledger carries one corpus.refresh event per run.
    events = [e for e in storage.iter_ledger_events() if e["event_type"] == "corpus.refresh"]
    assert len(events) == 1
    payload = json.loads(events[0]["payload_json"])
    assert payload["outcome_counts"] == {"ok": 1}

    # Stats carries the freshness state: fresh, within the bound.
    stats = storage.corpus_stats()
    assert stats["source_freshness"] is not None
    assert stats["source_freshness"]["summary"]["fresh"] == 1
    assert stats["source_freshness"]["stale_snapshot"] is False


def test_refresh_unchanged_is_idempotent(tmp_path: Path) -> None:
    root, storage, ledger = _setup(tmp_path, {"a.md": "# A\nalpha"})
    _ingest(root, storage, ledger)
    first = _refresh(root, storage, ledger)
    second = _refresh(root, storage, ledger)

    assert first["outcome_counts"] == {"ok": 1}
    assert second["outcome_counts"] == {"unchanged": 1}
    rows = _version_rows(storage, "a.md", str(root))
    assert len(rows) == 1, "idempotent replay creates no new version row"
    assert rows[0]["outcome"] == "ok"

    state = source_freshness(
        storage, root_path=str(root), rel_path="a.md",
        document_sha256=rows[0]["sha256"],
    )
    assert state["state"] == "fresh"


def test_refresh_changed_appends_new_version_same_source(tmp_path: Path) -> None:
    root, storage, ledger = _setup(tmp_path, {"a.md": "# A\nalpha"})
    _ingest(root, storage, ledger)
    _refresh(root, storage, ledger)
    (root / "a.md").write_text("# A\nbeta, changed", encoding="utf-8")
    summary = _refresh(root, storage, ledger)

    assert summary["outcome_counts"] == {"changed": 1}
    rows = _version_rows(storage, "a.md", str(root))
    assert len(rows) == 2
    assert [row["outcome"] for row in rows] == ["ok", "changed"]
    assert rows[0]["source_id"] == rows[1]["source_id"]
    assert rows[0]["sha256"] != rows[1]["sha256"]

    # The stored snapshot still holds the old bytes: stale, content changed.
    with storage.connection() as conn:
        doc_sha = conn.execute(
            "SELECT sha256 FROM documents WHERE rel_path = 'a.md'"
        ).fetchone()[0]
    state = source_freshness(
        storage, root_path=str(root), rel_path="a.md", document_sha256=str(doc_sha)
    )
    assert state["state"] == "stale"
    assert state["reason"] == "content_changed"


def test_refresh_deleted_marks_missing_and_planner_excludes(tmp_path: Path) -> None:
    root, storage, ledger = _setup(
        tmp_path, {"relevant.md": "# Foundations\nrecursive foundations"}
    )
    _ingest(root, storage, ledger)
    _refresh(root, storage, ledger)
    (root / "relevant.md").unlink()
    summary = _refresh(root, storage, ledger)

    assert summary["outcome_counts"] == {"deleted": 1}
    with storage.connection() as conn:
        doc = conn.execute(
            "SELECT id, sha256 FROM documents WHERE rel_path = 'relevant.md'"
        ).fetchone()
    state = source_freshness(
        storage, root_path=str(root), rel_path="relevant.md",
        document_sha256=str(doc["sha256"]),
    )
    assert state["state"] == "missing"
    assert state["reason"] == "deleted"

    planner = Planner(storage=storage, ledger=ledger, seed_dir=_seed_dir(tmp_path))
    plan = planner.generate(_profile(tmp_path))
    assert [c["rel_path"] for c in _candidates(plan)] == []
    assert plan["source_freshness"]["stale_snapshot"] is True
    assert plan["source_freshness"]["excluded_sources"] == [
        {
            "document_id": int(doc["id"]),
            "rel_path": "relevant.md",
            "state": "missing",
            "reason": "deleted",
        }
    ]


def test_refresh_timeout_records_failure_and_others_still_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, storage, ledger = _setup(
        tmp_path,
        {"slow.md": "# Slow\nslow content", "fast.md": "# Fast\nfast content"},
    )
    _ingest(root, storage, ledger)
    _refresh(root, storage, ledger)

    original_read = corpus_module._read_admitted_bytes

    def flaky_read(root_arg: Path, path: Path) -> bytes:
        if path.name == "slow.md":
            raise TimeoutError("simulated timeout")
        return original_read(root_arg, path)

    monkeypatch.setattr(corpus_module, "_read_admitted_bytes", flaky_read)
    summary = _refresh(root, storage, ledger)

    assert summary["outcome_counts"] == {"timeout": 1, "unchanged": 1}
    slow_rows = _version_rows(storage, "slow.md", str(root))
    assert slow_rows[-1]["outcome"] == "timeout"
    # The prior version stays usable-but-stale: failed, last good retained.
    with storage.connection() as conn:
        doc_sha = conn.execute(
            "SELECT sha256 FROM documents WHERE rel_path = 'slow.md'"
        ).fetchone()[0]
    state = source_freshness(
        storage, root_path=str(root), rel_path="slow.md",
        document_sha256=str(doc_sha),
    )
    assert state["state"] == "failed"
    assert state["reason"] == "timeout"
    assert state["last_good_retrieved_at"] is not None


def test_refresh_rate_limited_records_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, storage, ledger = _setup(tmp_path, {"a.md": "# A\nalpha"})
    _ingest(root, storage, ledger)
    _refresh(root, storage, ledger)

    def limited_read(root_arg: Path, path: Path) -> bytes:
        raise RateLimitError("simulated rate limit")

    monkeypatch.setattr(corpus_module, "_read_admitted_bytes", limited_read)
    summary = _refresh(root, storage, ledger)

    assert summary["outcome_counts"] == {"rate_limited": 1}
    rows = _version_rows(storage, "a.md", str(root))
    assert rows[-1]["outcome"] == "rate_limited"
    assert rows[-1]["sha256"] is None, "failure markers carry no bytes"
    # The last good version is still recoverable through the content rows.
    with storage.connection() as conn:
        doc_sha = conn.execute(
            "SELECT sha256 FROM documents WHERE rel_path = 'a.md'"
        ).fetchone()[0]
    state = source_freshness(
        storage, root_path=str(root), rel_path="a.md", document_sha256=str(doc_sha)
    )
    assert state["state"] == "failed"
    assert state["last_good_retrieved_at"] is not None


def test_refresh_revoked_refuses_and_planner_excludes(tmp_path: Path) -> None:
    root, storage, ledger = _setup(
        tmp_path, {"relevant.md": "# Foundations\nrecursive foundations"}
    )
    _ingest(root, storage, ledger)
    _refresh(root, storage, ledger)
    # The inventory now classifies the file private-never-in-git: admission
    # revoked. The bytes are never re-read.
    (root / "privacy-classification.yaml").write_text(
        "schema_version: '1.0'\nentries:\n"
        "  - patterns: ['relevant.md']\n    class: private-never-in-git\n",
        encoding="utf-8",
    )
    summary = _refresh(root, storage, ledger)

    # The inventory file itself is a newly observed source (ok); the revoked
    # file is the one that matters.
    assert summary["outcome_counts"] == {"ok": 1, "revoked": 1}
    assert {"rel_path": "relevant.md", "outcome": "revoked"} in summary["sources"]
    rows = _version_rows(storage, "relevant.md", str(root))
    assert rows[-1]["outcome"] == "revoked"
    assert rows[-1]["sha256"] is None, "revoked bytes are never read"

    planner = Planner(storage=storage, ledger=ledger, seed_dir=_seed_dir(tmp_path))
    plan = planner.generate(_profile(tmp_path))
    assert [c["rel_path"] for c in _candidates(plan)] == []
    assert plan["source_freshness"]["excluded_sources"][0]["state"] == "revoked"


def test_refresh_recovers_after_deletion(tmp_path: Path) -> None:
    root, storage, ledger = _setup(tmp_path, {"a.md": "# A\nalpha"})
    _ingest(root, storage, ledger)
    _refresh(root, storage, ledger)
    (root / "a.md").unlink()
    deleted = _refresh(root, storage, ledger)
    (root / "a.md").write_text("# A\nalpha", encoding="utf-8")
    recovered = _refresh(root, storage, ledger)

    assert deleted["outcome_counts"] == {"deleted": 1}
    assert recovered["outcome_counts"] == {"ok": 1}
    rows = _version_rows(storage, "a.md", str(root))
    assert [row["outcome"] for row in rows] == ["ok", "deleted", "ok"]
    assert json.loads(rows[-1]["detail_json"])["recovered_after"] == "deleted"

    with storage.connection() as conn:
        doc_sha = conn.execute(
            "SELECT sha256 FROM documents WHERE rel_path = 'a.md'"
        ).fetchone()[0]
    state = source_freshness(
        storage, root_path=str(root), rel_path="a.md", document_sha256=str(doc_sha)
    )
    assert state["state"] == "fresh"


def test_freshness_stale_by_age(tmp_path: Path) -> None:
    root, storage, ledger = _setup(tmp_path, {"a.md": "# A\nalpha"})
    _ingest(root, storage, ledger)
    _refresh(root, storage, ledger)
    rows = _version_rows(storage, "a.md", str(root))
    far_future = datetime.now(tz=UTC) + timedelta(hours=200)
    state = source_freshness(
        storage,
        root_path=str(root),
        rel_path="a.md",
        document_sha256=rows[0]["sha256"],
        now=far_future,
    )
    assert state["state"] == "stale"
    assert state["reason"] == "max_age_exceeded"


def test_freshness_unknown_before_any_refresh(tmp_path: Path) -> None:
    root, storage, ledger = _setup(tmp_path, {"a.md": "# A\nalpha"})
    _ingest(root, storage, ledger)
    with storage.connection() as conn:
        doc_sha = conn.execute(
            "SELECT sha256 FROM documents WHERE rel_path = 'a.md'"
        ).fetchone()[0]
    state = source_freshness(
        storage, root_path=str(root), rel_path="a.md", document_sha256=str(doc_sha)
    )
    assert state["state"] == "unknown"
    assert state["reason"] == "never_refreshed"


def test_refresh_never_promotes_candidate_to_support(tmp_path: Path) -> None:
    root, storage, ledger = _setup(
        tmp_path, {"relevant.md": "# Foundations\nrecursive foundations"}
    )
    snapshot = _ingest(root, storage, ledger)
    _refresh(root, storage, ledger)
    # Source admission (#48): refresh observes; only admission makes a
    # document a candidate.
    admit_all_documents(storage, snapshot.snapshot_id)
    planner = Planner(storage=storage, ledger=ledger, seed_dir=_seed_dir(tmp_path))
    plan = planner.generate(_profile(tmp_path))
    candidates = _candidates(plan)
    assert [c["rel_path"] for c in candidates] == ["relevant.md"]
    assert all(c["source_support"] == "source_support_unverified" for c in candidates)
    # The plan says it drew on a fresh source, and the fingerprint does not
    # move when only the confirmation time moves.
    assert plan["source_freshness"]["stale_snapshot"] is False
    assert plan["source_freshness"]["summary"]["fresh"] == 1
    second = planner.generate(_profile(tmp_path))
    assert second["plan_id"] == plan["plan_id"]


def test_corpus_refresh_cli_and_passage_freshness(tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "a.md").write_text("# A\nalpha", encoding="utf-8")
    db_path = tmp_path / "cli.db"
    runner = CliRunner()

    result = runner.invoke(
        cli, ["corpus", "ingest", "--root", str(root), "--snapshot", "s1",
              "--db-path", str(db_path)]
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(
        cli, ["corpus", "refresh", "--root", str(root), "--db-path", str(db_path)]
    )
    assert result.exit_code == 0, result.output
    summary = json.loads(result.output)
    assert summary["outcome_counts"] == {"ok": 1}

    storage = Storage(db_path)
    with storage.connection() as conn:
        doc = conn.execute("SELECT id FROM documents WHERE rel_path = 'a.md'").fetchone()
    result = runner.invoke(
        cli, ["corpus", "passage", str(doc["id"]), "0", "--db-path", str(db_path)]
    )
    assert result.exit_code == 0, result.output
    passage = json.loads(result.output)
    assert passage["freshness"]["state"] == "fresh"
