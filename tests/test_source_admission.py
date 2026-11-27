"""Tests for source admission (#48, MTR-017).

Fixtures are synthetic local corpora only — no real sources, no private
data. Admission is a recorded, attributed decision: ingest never
auto-admits, the planner selects only admitted passage-kind documents,
and a `private`-access decision redacts the source from every output.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from adaptive_personal_syllabus.admission import (
    admission_for_document,
    compute_content_kind,
    find_license_contradiction,
    validate_admission_record,
    validate_revocation_record,
)
from adaptive_personal_syllabus.core import cli
from adaptive_personal_syllabus.corpus import (
    CorpusIngestor,
    CorpusRefresher,
)
from adaptive_personal_syllabus.ledger import Ledger
from adaptive_personal_syllabus.planner import Planner
from adaptive_personal_syllabus.storage import Storage
from tests.admission_helpers import admit_all_documents, admit_document, admit_record
from tests.test_planner import _profile, _seed_dir


def _setup(tmp_path: Path, files: dict[str, bytes]) -> tuple[Path, Storage, Ledger, int]:
    """A synthetic corpus + storage + ledger; returns (root, storage, ledger, snapshot_id)."""
    root = tmp_path / "corpus"
    root.mkdir()
    for name, data in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    storage = Storage(tmp_path / "test.db")
    ledger = Ledger(storage)
    snapshot = CorpusIngestor(storage, ledger).ingest(root, "snap-1")
    return root, storage, ledger, snapshot.snapshot_id


def _admit_record(doc: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    return admit_record(doc, **overrides)


def _plan(tmp_path: Path, storage: Storage, ledger: Ledger) -> dict[str, Any]:
    seed = tmp_path / "seed"
    if not seed.exists():
        _seed_dir(tmp_path)
    planner = Planner(storage=storage, ledger=ledger, seed_dir=seed)
    return planner.generate(_profile(tmp_path))


def _candidates(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        candidate
        for module in plan["modules"]
        for candidate in module["source_selection"]["candidates"]
    ]


def _relevant_doc(tmp_path: Path) -> tuple[Path, Storage, Ledger, int, dict[str, Any]]:
    root, storage, ledger, snapshot_id = _setup(
        tmp_path, {"relevant.md": b"# Foundations\nrecursive foundations"}
    )
    docs = storage.list_documents(snapshot_id=snapshot_id)
    assert len(docs) == 1
    return root, storage, ledger, snapshot_id, docs[0]


def test_newly_ingested_documents_are_unadmitted_and_invisible_to_planner(
    tmp_path: Path,
) -> None:
    _, storage, ledger, _snapshot_id, doc = _relevant_doc(tmp_path)
    assert admission_for_document(storage, int(doc["id"]))["status"] == "unadmitted"
    assert _candidates(_plan(tmp_path, storage, ledger)) == []
    assert _plan(tmp_path, storage, ledger)["source_admission"]["summary"]["unadmitted"] == 1


def test_admission_makes_a_document_a_candidate(tmp_path: Path) -> None:
    _, storage, ledger, _snapshot_id, doc = _relevant_doc(tmp_path)
    admit_document(storage, doc)
    plan = _plan(tmp_path, storage, ledger)
    candidates = _candidates(plan)
    assert [c["rel_path"] for c in candidates] == ["relevant.md"]
    candidate = candidates[0]
    assert candidate["admission_status"] == "admitted"
    assert candidate["content_kind"] == "passage"
    assert candidate["document_completeness"] == "complete"
    assert candidate["source_support"] == "source_support_unverified"
    assert plan["source_admission"]["summary"]["admitted"] == 1
    assert plan["source_admission"]["excluded_sources"] == []


def test_ingest_and_refresh_never_auto_admit(tmp_path: Path) -> None:
    root, storage, ledger, _snapshot_id, doc = _relevant_doc(tmp_path)
    CorpusRefresher(storage, ledger).refresh(root)
    assert admission_for_document(storage, int(doc["id"]))["status"] == "unadmitted"
    assert _candidates(_plan(tmp_path, storage, ledger)) == []


def test_admit_requires_the_exact_sha(tmp_path: Path) -> None:
    _, storage, _ledger, _snapshot_id, doc = _relevant_doc(tmp_path)
    with pytest.raises(ValueError, match="sha256 mismatch"):
        validate_admission_record(storage, _admit_record(doc, sha256="0" * 64))
    with pytest.raises(ValueError, match="No document"):
        validate_admission_record(storage, _admit_record({**doc, "id": 999999}))


def test_sha_drift_invalidates_admission_until_re_admitted(tmp_path: Path) -> None:
    root, storage, ledger, _snapshot_id, doc = _relevant_doc(tmp_path)
    admit_document(storage, doc)
    assert _candidates(_plan(tmp_path, storage, ledger)) != []
    (root / "relevant.md").write_text(
        "# Foundations\nrecursive foundations, revised", encoding="utf-8"
    )
    new_snapshot = CorpusIngestor(storage, ledger).ingest(root, "snap-2")
    new_docs = storage.list_documents(snapshot_id=new_snapshot.snapshot_id)
    assert len(new_docs) == 1
    assert admission_for_document(storage, int(new_docs[0]["id"]))["status"] == "unadmitted"
    assert _candidates(_plan(tmp_path, storage, ledger)) == []
    admit_document(storage, new_docs[0])
    assert [c["rel_path"] for c in _candidates(_plan(tmp_path, storage, ledger))] == [
        "relevant.md"
    ]


def test_metadata_only_document_reports_kind_not_passage(tmp_path: Path) -> None:
    _, storage, ledger, snapshot_id = _setup(
        tmp_path,
        {
            "guide.md": b"# Foundations\nrecursive foundations",
            "paper.pdf": b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n",
        },
    )
    docs = {d["rel_path"]: d for d in storage.list_documents(snapshot_id=snapshot_id)}
    assert docs["paper.pdf"]["content_kind"] == "metadata_only"
    assert docs["guide.md"]["content_kind"] == "passage"
    assert storage.get_passage(int(docs["paper.pdf"]["id"]), 0) is None
    # Even admitted, a metadata-only document never becomes a candidate.
    admit_all_documents(storage, snapshot_id)
    candidates = _candidates(_plan(tmp_path, storage, ledger))
    assert [c["rel_path"] for c in candidates] == ["guide.md"]
    result = CliRunner().invoke(
        cli,
        ["corpus", "passage", str(docs["paper.pdf"]["id"]), "0",
         "--db-path", str(storage.db_path)],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["content_kind"] == "metadata_only"
    assert payload["text"] is None
    assert payload["document_completeness"] == "metadata_only"


def test_contradictory_license_refuses_admission(tmp_path: Path) -> None:
    _, storage, _ledger, snapshot_id = _setup(
        tmp_path,
        {"note.md": b"# Foundations\nAll rights reserved. Do not distribute.\nrecursive foundations"},
    )
    docs = storage.list_documents(snapshot_id=snapshot_id)
    assert find_license_contradiction(
        declared_license="CC0", embedded_text="All rights reserved."
    ) is not None
    assert find_license_contradiction(
        declared_license="Proprietary", embedded_text="public domain release"
    ) is not None
    assert (
        find_license_contradiction(
            declared_license="Internal license v3", embedded_text="All rights reserved."
        )
        is None
    )
    with pytest.raises(ValueError, match="license contradiction"):
        validate_admission_record(storage, _admit_record(docs[0], license="CC0"))
    # A matching declaration admits.
    admit_document(storage, docs[0], license="Proprietary — all rights reserved")
    assert admission_for_document(storage, int(docs[0]["id"]))["status"] == "admitted"


def test_revoked_document_leaves_planner_and_support(tmp_path: Path) -> None:
    root, storage, ledger, snapshot_id, doc = _relevant_doc(tmp_path)
    admit_document(storage, doc)
    assert _candidates(_plan(tmp_path, storage, ledger)) != []
    # One refresh before revocation, so a content version exists to
    # compare against after the revoke.
    CorpusRefresher(storage, ledger).refresh(root)
    chunk = storage.list_document_chunks(snapshot_id=snapshot_id)[0]
    record = {
        "document_id": chunk["document_id"],
        "snapshot_id": chunk["snapshot_id"],
        "sha256": chunk["sha256"],
        "chunk_index": chunk["chunk_index"],
        "claim": "Foundations need evidence.",
        "passage": chunk["text"],
        "span_start": 0,
        "span_end": len(chunk["text"]),
        "reason": "Synthetic fixture only.",
        # Human review attested by a human identity in docs/reviewers.yaml.
        "reviewer": "4jp",
        "reviewer_status": "human_reviewed",
        "judgment_method": "exact passage inspection",
        "reviewed_at": "2026-11-22",
        "judgment": "supports",
    }
    storage.record_source_judgment(record)
    revoke_record = validate_revocation_record(
        storage,
        {
            "document_id": int(doc["id"]),
            "sha256": str(doc["sha256"]),
            "revoked_by": "synthetic-operator",
            "revocation_reason": "source withdrawn by owner",
            "reviewed_at": "2026-11-22",
        },
    )
    storage.record_source_admission(revoke_record)
    assert admission_for_document(storage, int(doc["id"]))["status"] == "revoked"
    plan = _plan(tmp_path, storage, ledger)
    assert _candidates(plan) == []
    assert plan["source_admission"]["excluded_sources"][0]["reason"] == "admission_revoked"
    result = CliRunner().invoke(
        cli,
        ["corpus", "support", str(doc["id"]), "--claim", "Foundations need evidence.",
         "--db-path", str(storage.db_path)],
    )
    assert result.exit_code != 0
    assert "revoked" in result.output
    # Refresh records a revoked marker without re-reading bytes: change
    # the file after revocation and the refresh still says revoked, with
    # no new content version.
    (root / "relevant.md").write_text(
        "# Foundations\nrecursive foundations, changed after revoke", encoding="utf-8"
    )
    summary = CorpusRefresher(storage, ledger).refresh(root)
    assert summary["outcome_counts"] == {"revoked": 1}
    versions = storage.latest_content_version(
        int(storage.find_source_record(str(root), "relevant.md")["id"])
    )
    assert versions is not None
    assert str(versions["sha256"]) == str(doc["sha256"])


def test_rejected_document_is_excluded(tmp_path: Path) -> None:
    _, storage, ledger, _snapshot_id, doc = _relevant_doc(tmp_path)
    root_path = str(storage.get_document(int(doc["id"]))["root_path"])
    storage.record_source_admission(
        {
            "root_path": root_path,
            "rel_path": str(doc["rel_path"]),
            "sha256": str(doc["sha256"]),
            "document_id": int(doc["id"]),
            "decision": "rejected",
            "owner": "synthetic-owner",
            "license": "CC-BY-4.0",
            "access": "public",
            "provenance": "synthetic fixture",
            "admitted_by": "synthetic-operator",
            "admission_basis": "out of scope for this corpus",
            "reviewer": "synthetic-reviewer",
            "reviewed_at": "2026-11-22",
            "admitted_at": None,
            "revoked_by": None,
            "revocation_reason": None,
            "revoked_at": None,
        }
    )
    assert admission_for_document(storage, int(doc["id"]))["status"] == "rejected"
    assert _candidates(_plan(tmp_path, storage, ledger)) == []


def test_revoke_then_readmit(tmp_path: Path) -> None:
    _, storage, ledger, _snapshot_id, doc = _relevant_doc(tmp_path)
    admit_document(storage, doc)
    storage.record_source_admission(
        validate_revocation_record(
            storage,
            {
                "document_id": int(doc["id"]),
                "sha256": str(doc["sha256"]),
                "revoked_by": "synthetic-operator",
                "revocation_reason": "temporary withdrawal",
            },
        )
    )
    assert admission_for_document(storage, int(doc["id"]))["status"] == "revoked"
    admit_document(storage, doc)
    assert admission_for_document(storage, int(doc["id"]))["status"] == "admitted"
    assert _candidates(_plan(tmp_path, storage, ledger)) != []


def test_symlink_and_private_paths_are_never_admittable(tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "real.md").write_text("# Foundations\nrecursive foundations", encoding="utf-8")
    (root / "alias.md").symlink_to(root / "real.md")
    private = root / ".private"
    private.mkdir()
    (private / "secret.md").write_text("# Foundations\nrecursive foundations", encoding="utf-8")
    storage = Storage(tmp_path / "test.db")
    snapshot = CorpusIngestor(storage, Ledger(storage)).ingest(root, "snap-1")
    rel_paths = [d["rel_path"] for d in storage.list_documents(snapshot_id=snapshot.snapshot_id)]
    assert rel_paths == ["real.md"]
    with pytest.raises(ValueError, match="No document"):
        validate_admission_record(storage, _admit_record({"id": 999999, "sha256": "0" * 64}))


def test_private_access_never_leaks(tmp_path: Path) -> None:
    root, storage, ledger, _snapshot_id, doc = _relevant_doc(tmp_path)
    admit_document(storage, doc, access="private")
    stats = json.loads(
        CliRunner()
        .invoke(cli, ["corpus", "stats", "--db-path", str(storage.db_path)])
        .output
    )
    dumped = json.dumps(stats)
    assert "relevant.md" not in dumped
    assert "[redacted: private]" in dumped
    plan = _plan(tmp_path, storage, ledger)
    assert _candidates(plan) == []
    assert json.dumps(plan).count("relevant.md") == 0
    assert plan["source_admission"]["summary"].get("private_access") == 1
    result = CliRunner().invoke(
        cli,
        ["corpus", "passage", str(doc["id"]), "0", "--db-path", str(storage.db_path)],
    )
    assert result.exit_code != 0
    assert "Private source" in result.output
    result = CliRunner().invoke(
        cli,
        ["corpus", "support", str(doc["id"]), "--claim", "x",
         "--db-path", str(storage.db_path)],
    )
    assert result.exit_code != 0
    assert "Private source" in result.output
    summary = CorpusRefresher(storage, ledger).refresh(root)
    assert "relevant.md" not in json.dumps(summary)
    assert summary["sources"][0]["rel_path"] == "[redacted: private]"


def test_private_holdout_never_ingested(tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "guide.md").write_text("# Foundations\nrecursive foundations", encoding="utf-8")
    private = root / ".private"
    private.mkdir()
    (private / "holdout.md").write_text("private catalog entry", encoding="utf-8")
    storage = Storage(tmp_path / "test.db")
    snapshot = CorpusIngestor(storage, Ledger(storage)).ingest(root, "snap-1")
    rel_paths = [d["rel_path"] for d in storage.list_documents(snapshot_id=snapshot.snapshot_id)]
    assert rel_paths == ["guide.md"]
    stats = storage.corpus_stats(snapshot_id=snapshot.snapshot_id)
    assert "holdout.md" not in json.dumps(stats)


def test_admission_record_fields_persisted(tmp_path: Path) -> None:
    _, storage, _ledger, _snapshot_id, doc = _relevant_doc(tmp_path)
    admit_document(
        storage,
        doc,
        owner="synthetic-owner",
        license="CC-BY-4.0",
        access="restricted",
        provenance="https://example.invalid/source",
        admitted_by="synthetic-operator",
        admission_basis="license reviewed against inventory",
        reviewer="synthetic-reviewer",
        reviewed_at="2026-11-22",
    )
    row = storage.latest_source_admission(
        str(storage.get_document(int(doc["id"]))["root_path"]),
        "relevant.md",
        sha256=str(doc["sha256"]),
    )
    assert row is not None
    assert row["decision"] == "admitted"
    assert row["owner"] == "synthetic-owner"
    assert row["license"] == "CC-BY-4.0"
    assert row["access"] == "restricted"
    assert row["provenance"] == "https://example.invalid/source"
    assert row["admitted_by"] == "synthetic-operator"
    assert row["admission_basis"] == "license reviewed against inventory"
    assert row["reviewer"] == "synthetic-reviewer"
    assert row["reviewed_at"] == "2026-11-22"
    assert row["admitted_at"]


def test_cli_admit_and_revoke_roundtrip(tmp_path: Path) -> None:
    _, storage, ledger, _snapshot_id, doc = _relevant_doc(tmp_path)
    admit_path = tmp_path / "admit.json"
    admit_path.write_text(json.dumps(_admit_record(doc)), encoding="utf-8")
    result = CliRunner().invoke(
        cli, ["corpus", "admit", str(admit_path), "--db-path", str(storage.db_path)]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["record"]["decision"] == "admitted"
    assert admission_for_document(storage, int(doc["id"]))["status"] == "admitted"
    assert _candidates(_plan(tmp_path, storage, ledger)) != []
    revoke_path = tmp_path / "revoke.json"
    revoke_path.write_text(
        json.dumps(
            {
                "document_id": int(doc["id"]),
                "sha256": str(doc["sha256"]),
                "revoked_by": "synthetic-operator",
                "revocation_reason": "no longer usable",
            }
        ),
        encoding="utf-8",
    )
    result = CliRunner().invoke(
        cli, ["corpus", "revoke", str(revoke_path), "--db-path", str(storage.db_path)]
    )
    assert result.exit_code == 0, result.output
    assert admission_for_document(storage, int(doc["id"]))["status"] == "revoked"
    assert _candidates(_plan(tmp_path, storage, ledger)) == []
    # A wrong-sha admit fails loudly at the CLI, never silently.
    wrong_path = tmp_path / "wrong.json"
    wrong_path.write_text(
        json.dumps(_admit_record(doc, sha256="0" * 64)), encoding="utf-8"
    )
    result = CliRunner().invoke(
        cli, ["corpus", "admit", str(wrong_path), "--db-path", str(storage.db_path)]
    )
    assert result.exit_code != 0
    assert "sha256 mismatch" in result.output


def test_content_kind_classification() -> None:
    assert compute_content_kind("# text\n") == "passage"
    assert compute_content_kind("") == "passage"
    assert compute_content_kind(None) == "metadata_only"
    assert compute_content_kind(None, extraction_failed=True) == "extraction_failed"
    assert compute_content_kind("# text\n", extraction_failed=True) == "extraction_failed"


def test_admission_never_promotes_candidate_to_support(tmp_path: Path) -> None:
    _, storage, ledger, _snapshot_id, doc = _relevant_doc(tmp_path)
    admit_document(storage, doc)
    plan = _plan(tmp_path, storage, ledger)
    assert _candidates(plan)[0]["source_support"] == "source_support_unverified"
    assert plan["modules"][0]["source_selection"]["judgments"] == []
    assert (
        plan["modules"][0]["source_selection"]["claim_support_status"]
        == "source_support_unverified"
    )
