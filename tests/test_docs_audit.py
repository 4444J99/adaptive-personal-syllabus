"""Tests for docs audit ingestion, extraction, and classification."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from adaptive_personal_syllabus.docs_audit import (
    DocsAuditError,
    DocsAuditService,
    build_milestone_execution_plan,
    normalize_report_for_comparison,
    reports_match,
)
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


def _audit(root: Path, db: Path, snapshot: str = "test") -> dict:
    storage = Storage(db)
    return DocsAuditService(storage=storage, ledger=Ledger(storage)).audit(
        root=root,
        snapshot_name=snapshot,
    )


def _init_git_repo(path: Path) -> str:
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], check=True)
    (path / "README.md").write_text("# test\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "initial"], check=True)
    head = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return head


def _orphan_commit(path: Path) -> str:
    empty_tree = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
    proc = subprocess.run(
        ["git", "-C", str(path), "commit-tree", empty_tree, "-m", "stale"],
        check=True, capture_output=True, text=True,
    )
    return proc.stdout.strip()


def _write_verified_yaml(
    docs_root: Path,
    *,
    item_id: str,
    head: str,
    pr: int = 123,
    milestone: str = "integration-observability-ci",
    notes: str | None = None,
) -> None:
    milestone_dir = docs_root / "implementation" / "milestones"
    milestone_dir.mkdir(parents=True, exist_ok=True)
    body = (
        "schema_version: '1.0'\n"
        f"milestone: {milestone}\n"
        "verifications:\n"
        f"  - suggestion_id: {item_id}\n"
        f"    head: {head}\n"
        f"    pr: {pr}\n"
        "    checks:\n"
        "      - name: test (3.12)\n"
        "        run_id: 123456789\n"
        "        conclusion: success\n"
    )
    if notes is not None:
        body += f"notes: |\n  {notes}\n"
    (milestone_dir / "integration-observability-ci.verified.yaml").write_text(body, encoding="utf-8")


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
        ),
        encoding="utf-8",
    )

    second_report = service.audit(root=docs_root, snapshot_name="second")
    promoted = next(
        item for item in second_report["suggestions"]["items"] if item["id"] == ci_item["id"]
    )
    assert promoted["status"] == "planned"
    assert promoted["verification_status"] == "unverified"
    assert promoted["implementation_tags"] == []
    assert second_report["unmatched_implementation_claims"] == {}
    assert all(row["completion_pct"] is None for row in second_report["milestones"]["summary"])
    assert "milestone.integration-observability-ci" in promoted["implementation_claims"]


def test_docs_audit_unknown_status_id_is_rejected(tmp_path: Path) -> None:
    # #38: an unknown ID in a status file is a hard error, not a warning —
    # the old behavior recorded it in unmatched_implementation_claims and
    # kept going. The claim names an item the audit cannot see.
    docs_root = tmp_path / "docs"
    docs_root.mkdir()
    _build_docs(docs_root)

    milestone_dir = docs_root / "implementation" / "milestones"
    milestone_dir.mkdir(parents=True)
    (milestone_dir / "integration-observability-ci.status.yaml").write_text(
        (
            "schema_version: '1.0'\n"
            "milestone: integration-observability-ci\n"
            "implemented_suggestion_ids:\n"
            "  - feat-unknown\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(DocsAuditError, match="feat-unknown"):
        _audit(docs_root, tmp_path / "audit.db")


def test_docs_audit_keyword_only_item_is_never_promoted(tmp_path: Path) -> None:
    # #38: a keyword match feeds implementation_claims only. Even with a
    # status-yaml claim on top, the item stays planned with empty tags —
    # the old generator's keyword promotion path stays closed.
    docs_root = tmp_path / "docs"
    docs_root.mkdir()
    _build_docs(docs_root)

    storage = Storage(tmp_path / "audit.db")
    service = DocsAuditService(storage=storage, ledger=Ledger(storage))
    first_report = service.audit(root=docs_root, snapshot_name="first")
    hashing_item = next(
        item
        for item in first_report["suggestions"]["items"]
        if item["text"] == "Add cryptographic hashing protocols to the SOP for prompt logging"
    )
    assert "ledger.hash-chain-and-provenance" in hashing_item["implementation_claims"]

    milestone_dir = docs_root / "implementation" / "milestones"
    milestone_dir.mkdir(parents=True)
    (milestone_dir / "integration-observability-ci.status.yaml").write_text(
        (
            "schema_version: '1.0'\n"
            "milestone: integration-observability-ci\n"
            "implemented_suggestion_ids:\n"
            f"  - {hashing_item['id']}\n"
        ),
        encoding="utf-8",
    )

    second_report = service.audit(root=docs_root, snapshot_name="second")
    item = next(
        item for item in second_report["suggestions"]["items"] if item["id"] == hashing_item["id"]
    )
    assert item["status"] == "planned"
    assert item["verification_status"] == "unverified"
    assert item["implementation_tags"] == []
    assert "ledger.hash-chain-and-provenance" in item["implementation_claims"]
    assert "milestone.integration-observability-ci" in item["implementation_claims"]


def test_docs_audit_unknown_verification_id_is_rejected(tmp_path: Path) -> None:
    docs_root = tmp_path / "docs"
    docs_root.mkdir()
    _build_docs(docs_root)

    milestone_dir = docs_root / "implementation" / "milestones"
    milestone_dir.mkdir(parents=True)
    (milestone_dir / "integration-observability-ci.verified.yaml").write_text(
        (
            "schema_version: '1.0'\n"
            "milestone: integration-observability-ci\n"
            "verifications:\n"
            "  - suggestion_id: feat-unknown\n"
            f"    head: {'a' * 40}\n"
            "    pr: 123\n"
            "    checks:\n"
            "      - name: test (3.12)\n"
            "        run_id: 123456789\n"
            "        conclusion: success\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(DocsAuditError, match="feat-unknown"):
        _audit(docs_root, tmp_path / "audit.db")


@pytest.mark.parametrize(
    "yaml_body",
    [
        # Missing checks.
        (
            "schema_version: '1.0'\n"
            "milestone: integration-observability-ci\n"
            "verifications:\n"
            "  - suggestion_id: feat-placeholder\n"
            f"    head: {'a' * 40}\n"
            "    pr: 123\n"
        ),
        # Head is not a full SHA.
        (
            "schema_version: '1.0'\n"
            "milestone: integration-observability-ci\n"
            "verifications:\n"
            "  - suggestion_id: feat-placeholder\n"
            "    head: abc123\n"
            "    pr: 123\n"
            "    checks:\n"
            "      - name: test (3.12)\n"
            "        run_id: 123456789\n"
            "        conclusion: success\n"
        ),
        # Cited check did not succeed: failed evidence is not evidence.
        (
            "schema_version: '1.0'\n"
            "milestone: integration-observability-ci\n"
            "verifications:\n"
            "  - suggestion_id: feat-placeholder\n"
            f"    head: {'a' * 40}\n"
            "    pr: 123\n"
            "    checks:\n"
            "      - name: test (3.12)\n"
            "        run_id: 123456789\n"
            "        conclusion: failure\n"
        ),
    ],
)
def test_docs_audit_malformed_verification_is_rejected(tmp_path: Path, yaml_body: str) -> None:
    docs_root = tmp_path / "docs"
    docs_root.mkdir()
    _build_docs(docs_root)

    storage = Storage(tmp_path / "audit.db")
    service = DocsAuditService(storage=storage, ledger=Ledger(storage))
    first_report = service.audit(root=docs_root, snapshot_name="first")
    known_id = first_report["suggestions"]["items"][0]["id"]
    yaml_body = yaml_body.replace("feat-placeholder", known_id)

    milestone_dir = docs_root / "implementation" / "milestones"
    milestone_dir.mkdir(parents=True)
    (milestone_dir / "integration-observability-ci.verified.yaml").write_text(
        yaml_body, encoding="utf-8"
    )

    with pytest.raises(DocsAuditError):
        service.audit(root=docs_root, snapshot_name="second")


@pytest.mark.skipif(shutil.which("git") is None, reason="git required for ancestry checks")
def test_docs_audit_valid_verification_promotes_item(tmp_path: Path) -> None:
    docs_root = tmp_path / "docs"
    docs_root.mkdir()
    _build_docs(docs_root)

    storage = Storage(tmp_path / "audit.db")
    service = DocsAuditService(storage=storage, ledger=Ledger(storage))
    first_report = service.audit(root=docs_root, snapshot_name="first")
    ci_item = next(
        item for item in first_report["suggestions"]["items"] if item["text"] == "Define CI pipelines for kernel builds"
    )

    head = _init_git_repo(tmp_path)
    _write_verified_yaml(docs_root, item_id=ci_item["id"], head=head)

    second_report = service.audit(
        root=docs_root, snapshot_name="second", audited_head=head
    )
    item = next(
        item for item in second_report["suggestions"]["items"] if item["id"] == ci_item["id"]
    )
    assert item["status"] == "implemented"
    assert item["verification_status"] == "verified"
    assert item["implementation_tags"] == ["milestone.integration-observability-ci"]
    assert item["verification"]["head"] == head
    assert item["verification"]["pr"] == 123
    assert item["verification"]["checks"] == [
        {"name": "test (3.12)", "run_id": 123456789, "conclusion": "success"}
    ]
    assert second_report["rejected_verifications"] == []
    assert second_report["suggestions"]["implemented_count"] == 1
    summary = {
        row["milestone_id"]: row for row in second_report["milestones"]["summary"]
    }
    assert summary["integration-observability-ci"]["implemented_count"] == 1
    assert summary["integration-observability-ci"]["implemented_count"] == (
        second_report["suggestions"]["implemented_count"]
    )


@pytest.mark.skipif(shutil.which("git") is None, reason="git required for ancestry checks")
def test_docs_audit_stale_head_verification_is_rejected(tmp_path: Path) -> None:
    # A record whose head is a real commit but not an ancestor of the
    # audited head is rejected with a reason and listed — not silently
    # dropped and not silently promoted.
    docs_root = tmp_path / "docs"
    docs_root.mkdir()
    _build_docs(docs_root)

    storage = Storage(tmp_path / "audit.db")
    service = DocsAuditService(storage=storage, ledger=Ledger(storage))
    first_report = service.audit(root=docs_root, snapshot_name="first")
    ci_item = next(
        item for item in first_report["suggestions"]["items"] if item["text"] == "Define CI pipelines for kernel builds"
    )

    head = _init_git_repo(tmp_path)
    stale_head = _orphan_commit(tmp_path)
    _write_verified_yaml(docs_root, item_id=ci_item["id"], head=stale_head)

    second_report = service.audit(
        root=docs_root, snapshot_name="second", audited_head=head
    )
    item = next(
        item for item in second_report["suggestions"]["items"] if item["id"] == ci_item["id"]
    )
    assert item["status"] == "planned"
    assert item["verification_status"] == "unverified"
    assert item["implementation_tags"] == []
    assert len(second_report["rejected_verifications"]) == 1
    rejected = second_report["rejected_verifications"][0]
    assert rejected["suggestion_id"] == ci_item["id"]
    assert rejected["reason"] == "stale-head"


@pytest.mark.skipif(shutil.which("git") is None, reason="git required for ancestry checks")
def test_docs_audit_unverifiable_head_verification_is_rejected(tmp_path: Path) -> None:
    # A well-formed record whose head does not exist in this checkout
    # cannot be ancestry-checked, so it is rejected as unverifiable —
    # never trusted on the yaml's word alone.
    docs_root = tmp_path / "docs"
    docs_root.mkdir()
    _build_docs(docs_root)

    storage = Storage(tmp_path / "audit.db")
    service = DocsAuditService(storage=storage, ledger=Ledger(storage))
    first_report = service.audit(root=docs_root, snapshot_name="first")
    ci_item = next(
        item for item in first_report["suggestions"]["items"] if item["text"] == "Define CI pipelines for kernel builds"
    )

    head = _init_git_repo(tmp_path)
    _write_verified_yaml(docs_root, item_id=ci_item["id"], head="b" * 40)

    second_report = service.audit(
        root=docs_root, snapshot_name="second", audited_head=head
    )
    item = next(
        item for item in second_report["suggestions"]["items"] if item["id"] == ci_item["id"]
    )
    assert item["status"] == "planned"
    assert item["verification_status"] == "unverified"
    assert len(second_report["rejected_verifications"]) == 1
    assert second_report["rejected_verifications"][0]["reason"] == "unverifiable-head"


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

    # #38: a .verified.yaml is never ingested as a suggestion source, even
    # when its free-form notes carry a bullet that would extract as an
    # item if the file were read as discovery text. The record itself is
    # rejected here (no git checkout, so no audited head) and listed.
    ci_item = next(
        item for item in first["suggestions"]["items"] if item["text"] == "Define CI pipelines for kernel builds"
    )
    _write_verified_yaml(
        root,
        item_id=ci_item["id"],
        head="c" * 40,
        notes="- Add a fake suggestion planted in a verification file.",
    )
    third = service.audit(root=root, snapshot_name="third")
    assert third["suggestions"]["items"] == first["suggestions"]["items"]
    assert len(third["rejected_verifications"]) == 1
    assert third["rejected_verifications"][0]["reason"] == "no-audited-head"


def test_docs_audit_regeneration_reproduces_committed_report(tmp_path: Path) -> None:
    # #38 step 6 / drift-gate property: two audits of the same tree
    # reproduce each other once run-varying metadata is normalized, and a
    # real doc change breaks the match. No network involved.
    docs_root = tmp_path / "docs"
    docs_root.mkdir()
    _build_docs(docs_root)

    first = _audit(docs_root, tmp_path / "first.db", snapshot="first")
    second = _audit(docs_root, tmp_path / "second.db", snapshot="second")
    assert first != second  # generated_at / snapshot differ between runs
    assert normalize_report_for_comparison(first) == normalize_report_for_comparison(second)
    assert reports_match(first, second)

    (docs_root / "d.md").write_text(
        "- Actionable Suggestions: Add a new suggestion after the baseline.\n",
        encoding="utf-8",
    )
    third = _audit(docs_root, tmp_path / "third.db", snapshot="third")
    assert not reports_match(first, third)
    assert third["suggestions"]["count"] == first["suggestions"]["count"] + 1


def test_docs_audit_drift_gate_ignores_self_outputs(tmp_path: Path) -> None:
    # #38: the committed report is regenerated with in-tree outputs (the
    # CLI excludes its write targets from discovery), while CI regenerates
    # with out-of-tree outputs (the report and roadmap appear in the
    # manifest with hashes one regeneration behind). The drift gate must
    # still match across the two paths — and must still fail on a real
    # doc change.
    docs_root = tmp_path / "docs"
    docs_root.mkdir()
    _build_docs(docs_root)

    report_path = docs_root / "implementation" / "docs-audit-report.json"
    roadmap_path = docs_root / "implementation" / "docs-audit-roadmap.md"
    report_path.parent.mkdir(parents=True)
    report_path.write_text('{"artifact_kind": "generated-docs-audit"}', encoding="utf-8")
    roadmap_path.write_text("<!-- aps-generated: discovery-output -->\n", encoding="utf-8")

    # Commit path: outputs excluded from discovery (what the CLI does when
    # --write-json/--write-md point inside the tree).
    storage = Storage(tmp_path / "first.db")
    in_tree = DocsAuditService(storage=storage, ledger=Ledger(storage)).audit(
        root=docs_root,
        snapshot_name="first",
        exclude_paths={report_path.resolve(), roadmap_path.resolve()},
    )
    # CI path: outputs outside the tree, no exclusion.
    out_of_tree = _audit(docs_root, tmp_path / "second.db", snapshot="second")

    assert len(in_tree["files"]) == len(out_of_tree["files"]) - 2
    assert in_tree != out_of_tree
    assert reports_match(in_tree, out_of_tree)
    assert normalize_report_for_comparison(in_tree) == normalize_report_for_comparison(
        out_of_tree
    )

    (docs_root / "d.md").write_text(
        "- Actionable Suggestions: Add a new suggestion after the baseline.\n",
        encoding="utf-8",
    )
    changed = _audit(docs_root, tmp_path / "third.db", snapshot="third")
    assert not reports_match(in_tree, changed)


def test_docs_audit_new_contract_files_add_no_suggestions(tmp_path: Path) -> None:
    # #38: the evidence-status contract, the reconciliation file, and the
    # regenerated report feed the audit as inventory, never as new
    # intentions. Guards the new files' wording: a future edit that adds
    # an extractable bullet to the contract fails here, not in CI.
    repo_docs = Path(__file__).resolve().parents[1] / "docs"
    contract = repo_docs / "implementation" / "contracts" / "evidence-status-contract.md"
    reconciliation = repo_docs / "implementation" / "docs-audit-reconciliation.json"
    assert contract.exists(), "evidence-status-contract.md must exist in the tree"
    assert reconciliation.exists(), "docs-audit-reconciliation.json must exist in the tree"

    docs_root = tmp_path / "docs"
    docs_root.mkdir()
    _build_docs(docs_root)
    baseline = _audit(docs_root, tmp_path / "first.db", snapshot="first")
    baseline_ids = {item["id"] for item in baseline["suggestions"]["items"]}

    target_contract = docs_root / "implementation" / "contracts"
    target_contract.mkdir(parents=True)
    (target_contract / "evidence-status-contract.md").write_text(
        contract.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (docs_root / "implementation" / "docs-audit-reconciliation.json").write_text(
        reconciliation.read_text(encoding="utf-8"), encoding="utf-8"
    )

    second = _audit(docs_root, tmp_path / "second.db", snapshot="second")
    assert {item["id"] for item in second["suggestions"]["items"]} == baseline_ids
    assert second["suggestions"]["items"] == baseline["suggestions"]["items"]
