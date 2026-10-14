"""Tests for docs audit ingestion, extraction, and classification."""

from __future__ import annotations

from pathlib import Path

from adaptive_personal_syllabus.docs_audit import DocsAuditService, build_milestone_execution_plan
from adaptive_personal_syllabus.ledger import Ledger
from adaptive_personal_syllabus.storage import Storage


def _build_docs(root: Path) -> None:
    (root / "a.md").write_text(
        (
            "# Critique\n"
            "- **Actionable Suggestions**: 1. Add cryptographic hashing protocols to the SOP for prompt "
            "logging. 2. Add step-by-step exercises with incremental milestones.\n"
            "- Use Case: Link repository metadata to ChainBlockARK logs.\n"
        ),
        encoding="utf-8",
    )
    # Duplicate payload on purpose.
    (root / "b.md").write_text((root / "a.md").read_text(encoding="utf-8"), encoding="utf-8")
    (root / "c.txt").write_text(
        "- Actionable Suggestions: Define CI pipelines for kernel builds.\n",
        encoding="utf-8",
    )


def test_docs_audit_ingests_every_file_and_tracks_status(tmp_path: Path) -> None:
    docs_root = tmp_path / "docs"
    docs_root.mkdir()
    _build_docs(docs_root)

    storage = Storage(tmp_path / "audit.db")
    ledger = Ledger(storage)
    report = DocsAuditService(storage=storage, ledger=ledger).audit(
        root=docs_root,
        snapshot_name="docs-test",
    )

    assert report["ingest_verification"]["all_files_ingested"] is True
    assert report["ingest_verification"]["expected_file_count"] == 3
    assert report["snapshot"]["doc_count"] == 3
    assert len(report["files"]) == 3

    duplicate = next(item for item in report["files"] if item["rel_path"] == "b.md")
    assert duplicate["is_duplicate_payload"] is True

    by_text = {item["text"]: item for item in report["suggestions"]["items"]}
    hashing_item = by_text["Add cryptographic hashing protocols to the SOP for prompt logging"]
    exercises_item = by_text["Add step-by-step exercises with incremental milestones"]
    ci_item = by_text["Define CI pipelines for kernel builds"]

    assert hashing_item["status"] == "planned"
    assert hashing_item["verification_status"] == "unverified"
    assert "ledger.hash-chain-and-provenance" in hashing_item["implementation_claims"]
    assert exercises_item["status"] == "planned"
    assert exercises_item["planned_milestone"] == "pedagogy-scaffolding"
    assert ci_item["status"] == "planned"
    assert ci_item["planned_milestone"] == "systems-kernel-runtime"

    assert report["use_cases"]["count"] >= 1
    assert report["milestones"]["summary"]
    assert report["milestones"]["recommended_start_milestone"] is not None


def test_docs_audit_status_override_preserves_claim_without_promoting(tmp_path: Path) -> None:
    docs_root = tmp_path / "docs"
    docs_root.mkdir()
    _build_docs(docs_root)

    storage = Storage(tmp_path / "audit.db")
    ledger = Ledger(storage)
    service = DocsAuditService(storage=storage, ledger=ledger)
    first_report = service.audit(root=docs_root, snapshot_name="first")
    ci_item = next(
        item for item in first_report["suggestions"]["items"] if item["text"] == "Define CI pipelines for kernel builds"
    )
    assert ci_item["status"] == "planned"

    milestone_dir = docs_root / "implementation" / "milestones"
    milestone_dir.mkdir(parents=True)
    (milestone_dir / "integration-observability-ci.status.yaml").write_text(
        (
            "schema_version: '1.0'\n"
            "milestone: integration-observability-ci\n"
            "implemented_suggestion_ids:\n"
            f"  - {ci_item['id']}\n"
            "  - feat-unknown\n"
        ),
        encoding="utf-8",
    )

    second_report = service.audit(root=docs_root, snapshot_name="second")
    promoted = next(
        item for item in second_report["suggestions"]["items"] if item["id"] == ci_item["id"]
    )
    assert promoted["status"] == "planned"
    assert promoted["verification_status"] == "unverified"
    assert second_report["unmatched_implementation_claims"] == {"feat-unknown": "integration-observability-ci"}
    assert all(row["completion_pct"] is None for row in second_report["milestones"]["summary"])
    assert "milestone.integration-observability-ci" in promoted["implementation_claims"]


def test_build_milestone_execution_plan_ranks_items(tmp_path: Path) -> None:
    docs_root = tmp_path / "docs"
    docs_root.mkdir()
    _build_docs(docs_root)

    storage = Storage(tmp_path / "audit.db")
    ledger = Ledger(storage)
    report = DocsAuditService(storage=storage, ledger=ledger).audit(
        root=docs_root,
        snapshot_name="plan-test",
    )

    plan = build_milestone_execution_plan(
        report,
        milestone="systems-kernel-runtime",
        limit=5,
    )
    assert plan["milestone"] == "systems-kernel-runtime"
    assert plan["selected_item_count"] >= 1
    assert plan["selected_items"][0]["id"].startswith("feat-")


def test_generated_reports_do_not_become_new_intentions(tmp_path: Path) -> None:
    from adaptive_personal_syllabus.docs_audit import render_audit_markdown

    root = tmp_path / "docs"
    root.mkdir()
    _build_docs(root)
    storage = Storage(tmp_path / "audit.db")
    service = DocsAuditService(storage, Ledger(storage))
    first = service.audit(root=root, snapshot_name="first")
    (root / "custom-report.md").write_text(render_audit_markdown(first))
    legacy = root / "implementation" / "milestones"
    legacy.mkdir(parents=True)
    (legacy / "current-execution-plan.md").write_text("- Add invented output-only requirement.\n")
    second = service.audit(root=root, snapshot_name="second")
    assert second["suggestions"]["items"] == first["suggestions"]["items"]
    assert second["snapshot"]["doc_count"] == 5
    assert second["suggestions"]["implemented_count"] == 0
