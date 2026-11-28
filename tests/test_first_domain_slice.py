"""First world-studies slice (#59, MTR-028): one source, one module, one encounter.

Synthetic learner data only; the source passage is the real public-domain
Herodotus excerpt committed in ``data/slices/``. The suite proves the slice
loop end to end through the public machinery (ingest -> admit -> generate
-> encounter -> complete -> judge -> support) and pins the honest
boundary: an assistant judgment never flips ``claim_support_status`` to
``human_reviewed_support`` — only a human review does, and the loop
records none.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from adaptive_personal_syllabus.admission import validate_admission_record
from adaptive_personal_syllabus.core import cli
from adaptive_personal_syllabus.corpus import CorpusIngestor
from adaptive_personal_syllabus.encounter import adapt_encounter, complete_encounter
from adaptive_personal_syllabus.ledger import Ledger
from adaptive_personal_syllabus.planner import Planner
from adaptive_personal_syllabus.slices import load_slices, slice_modules_for
from adaptive_personal_syllabus.storage import Storage
from adaptive_personal_syllabus.support import summarize_judgments, validate_judgment
from tests.admission_helpers import admit_record
from tests.test_planner import _seed_dir

REPO_ROOT = Path(__file__).resolve().parents[1]
SLICE_DIR = REPO_ROOT / "data" / "slices"
EXCERPT = SLICE_DIR / "herodotus-nile-flood.md"
REGISTRY = SLICE_DIR / "world-studies-first-slice.json"

MODULE_ID = "world-studies-nile-flood-beg"
# The claim the slice's judged passage is evidence for: Herodotus refutes
# the Etesian-winds theory with observed counterexamples. The passage
# states the theory and then refutes it, so a "supports" judgment on this
# claim is the honest one — the opposite claim (that the winds cause the
# rise) is what the passage refutes.
CLAIM = "Herodotus refutes the Etesian-winds theory with observed counterexamples."
ETESIAN_START = "One pretends that the Etesian winds cause the rise of the"
ETESIAN_END = "entirely unlike the Nile in\nthis respect."


def _excerpt_root(tmp_path: Path) -> Path:
    root = tmp_path / "sources"
    root.mkdir()
    shutil.copy(EXCERPT, root / EXCERPT.name)
    return root


def _ingest_and_admit(tmp_path: Path) -> tuple[Storage, int, dict[str, Any]]:
    """Ingest the committed excerpt and admit it as the public-domain source."""
    storage = Storage(tmp_path / "slice.db")
    ledger = Ledger(storage)
    snapshot = CorpusIngestor(storage, ledger).ingest(
        _excerpt_root(tmp_path), "world-studies-first-slice"
    )
    docs = storage.list_documents(snapshot_id=snapshot.snapshot_id)
    assert len(docs) == 1
    doc = docs[0]
    record = admit_record(
        doc,
        owner="Herodotus",
        license="Public domain",
        access="public",
        provenance=(
            "Wikisource, The History of Herodotus (Rawlinson)/Book 2, "
            "revision 7044570 (2017-10-13T09:17:51Z)"
        ),
        admitted_by="synthetic-operator",
        admission_basis="public-domain source review",
        reviewed_at="2026-11-28",
    )
    normalized = validate_admission_record(storage, record)
    storage.record_source_admission(normalized)
    return storage, snapshot.snapshot_id, doc


def _world_studies_profile(tmp_path: Path, **changes: object) -> Path:
    profile_path = tmp_path / "profile.json"
    data = {
        "name": "Synthetic Learner",
        "organs_of_interest": ["world-studies"],
        "level": "beginner",
        "goals": ["synthetic-goal-world-studies"],
        "context": {},
        "completed_modules": [],
        "output_policy": {"selected_wings": []},
    }
    data.update(changes)
    profile_path.write_text(json.dumps(data), encoding="utf-8")
    return profile_path


def _generate(tmp_path: Path, storage: Storage) -> dict[str, Any]:
    ledger = Ledger(storage)
    planner = Planner(storage=storage, ledger=ledger, seed_dir=_seed_dir(tmp_path))
    return planner.generate(_world_studies_profile(tmp_path))


def _etesian_paragraph(chunk_text: str) -> str:
    """The Etesian paragraph inside the three-theories chunk, verbatim.

    The paragraph spans the source's hard-wrapped lines, so the markers
    stop at line breaks rather than assuming the words share one line.
    """
    start = chunk_text.index(ETESIAN_START)
    end = chunk_text.index(ETESIAN_END) + len(ETESIAN_END)
    return chunk_text[start:end]


def test_slice_registry_matches_committed_excerpt() -> None:
    slices = load_slices(SLICE_DIR)
    assert [s["slice_id"] for s in slices] == ["world-studies-first-slice"]
    entry = slices[0]
    assert entry["domain"] == "world-studies"
    assert entry["module"]["module_id"] == MODULE_ID
    assert entry["evaluation"]["criterion"] == "explain_with_counterexample"
    committed = EXCERPT.read_bytes()
    assert entry["source"]["sha256"] == hashlib.sha256(committed).hexdigest(), (
        "registry sha256 must match the committed excerpt bytes"
    )
    assert entry["source"]["file"] == "data/slices/herodotus-nile-flood.md"
    modules = slice_modules_for(["world-studies"], SLICE_DIR)
    assert [m.module_id for m in modules] == [MODULE_ID]
    assert modules[0].prerequisites and len(modules[0].prerequisites) == 1
    assert slice_modules_for(["I"], SLICE_DIR) == []
    assert slice_modules_for([], SLICE_DIR) == []


def test_registry_rejects_malformed_slice(tmp_path: Path) -> None:
    registry = tmp_path / "registry"
    registry.mkdir()
    (registry / "bad.json").write_text(
        json.dumps({"slices": [{"slice_id": "bad", "domain": "x"}]}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="requires non-empty"):
        load_slices(registry)
    assert load_slices(tmp_path / "absent") == []


def test_slice_module_reaches_plan_generate(tmp_path: Path) -> None:
    storage, _, _ = _ingest_and_admit(tmp_path)
    plan = _generate(tmp_path, storage)

    assert plan["totals"]["module_count"] == 1
    (module,) = plan["modules"]
    assert module["module_id"] == MODULE_ID
    assert module["title"] == "Why the Nile Floods in Summer"
    assert module["prerequisites"] and len(module["prerequisites"]) == 1
    assert module["readings"] == [
        "Herodotus, Histories Book 2 — The Nile Flood (Rawlinson translation)"
    ]
    selection = module["source_selection"]
    assert selection["claim_support_status"] == "source_support_unverified"
    assert "human-reviewed" in (selection["missing_support"] or "")
    paths = [c["canonical_path"] for c in selection["candidates"]]
    assert paths and all(p.endswith("herodotus-nile-flood.md") for p in paths)
    # Lexical ranking surfaces the problem chunk first; the three-theories
    # chunk ranks below the top 3 (it carries neither "summer" nor "why"),
    # but judgments attach by document, not by chunk, so the Etesian
    # passage is still judgeable for this module (see the judgment test).
    assert any(c["locator"] == "chunk:1" for c in selection["candidates"])
    # The slice module flows through the same machinery as organ modules.
    assert module["adaptation"]["route"] == "prerequisite_check"
    assert module["adaptation"]["assessment_status"] == "unassessed"
    assert plan["source_admission"]["summary"].get("admitted") == 1


def test_slice_encounter_routes_prerequisite_check_and_completes(
    tmp_path: Path,
) -> None:
    storage, _, _ = _ingest_and_admit(tmp_path)
    plan = _generate(tmp_path, storage)
    (module,) = plan["modules"]

    # The plan's "first_encounter expected" is wrong at this head: one
    # prerequisite routes to prerequisite_check (encounter.py). The slice
    # records the observed route; the evidence wins over the plan.
    decision, encounter = adapt_encounter(
        {"learning_purpose": "evaluate", "prior_task_evidence": []}, module
    )
    assert decision["route"] == "prerequisite_check"
    assert decision["assessment_status"] == "unassessed"
    assert any(module["prerequisites"][0] in step for step in encounter["steps"])

    receipt = complete_encounter(
        decision,
        encounter,
        {
            "module_id": MODULE_ID,
            "response_route": "short_written",
            "learner_words": (
                "Synthetic response: the Etesian winds cannot be the cause, "
                "because the Nile has risen when they did not blow."
            ),
        },
    )
    assert receipt["response_locator"].startswith("receipt:")
    assert receipt["assessment_status"] == "unassessed"
    assert "prerequisite_check" in receipt["next_instruction_basis"]
    assert receipt["module_id"] == MODULE_ID
    # The receipt round-trips through the ledger as its own payload.
    ledger = Ledger(storage)
    event = ledger.append("encounter.receipt", receipt)
    assert event.event_hash
    rows = list(storage.iter_ledger_events())
    stored = [
        json.loads(row["payload_json"]) for row in rows if row["event_type"] == "encounter.receipt"
    ]
    assert stored == [receipt]
    ok, errors, _ = Ledger(storage).verify_chain()
    assert ok, errors


def test_assistant_judgment_does_not_flip_support_status(tmp_path: Path) -> None:
    storage, snapshot_id, _ = _ingest_and_admit(tmp_path)
    chunks = storage.list_document_chunks(snapshot_id=snapshot_id)
    theories = next(c for c in chunks if "three theories" in c["heading_path"])
    passage = _etesian_paragraph(theories["text"])
    span_start = theories["text"].index(passage)

    record = {
        "document_id": int(theories["document_id"]),
        "snapshot_id": snapshot_id,
        "sha256": str(theories["sha256"]),
        "chunk_index": int(theories["chunk_index"]),
        "claim": CLAIM,
        "passage": passage,
        "span_start": span_start,
        "span_end": span_start + len(passage),
        "reason": (
            "Synthetic fixture only: the reviewer read the exact quoted "
            "passage; the judgment records inspection, not the truth of "
            "Herodotus's own sun theory."
        ),
        "reviewer": "synthetic-reviewer",
        "reviewer_status": "assistant_reviewed",
        "judgment_method": "span-grounded inspection",
        "reviewed_at": "2026-11-28",
        "judgment": "supports",
    }
    validate_judgment(storage, record)
    storage.record_source_judgment(record)
    summary = summarize_judgments(storage.list_source_judgments(snapshot_id=snapshot_id), CLAIM)
    # An assistant judgment is recorded and visible — but it does not flip
    # the status: only a human-reviewed supports does (support.py).
    assert summary["status"] == "source_support_unverified"
    assert len(summary["judgments"]) == 1
    assert summary["judgments"][0]["source_support"] == "source_support_unverified"

    plan = _generate(tmp_path, storage)
    (module,) = plan["modules"]
    assert module["source_selection"]["claim_support_status"] == "source_support_unverified"
    assert len(module["source_selection"]["judgments"]) == 1
    # A judgment IS attached (missing_support is None), yet the status
    # stays unverified: the attached judgment is assistant review, and
    # only human review flips it.
    assert module["source_selection"]["missing_support"] is None


def test_slice_loop_runs_through_cli(tmp_path: Path) -> None:
    runner = CliRunner()
    db = tmp_path / "cli.db"
    root = _excerpt_root(tmp_path)
    result = runner.invoke(
        cli,
        ["corpus", "ingest", "--root", str(root), "--snapshot", "cli-slice", "--db-path", str(db)],
    )
    assert result.exit_code == 0, result.output
    storage = Storage(db)
    docs = storage.list_documents(snapshot_id=1)
    assert len(docs) == 1
    admit_path = tmp_path / "admit.json"
    admit_path.write_text(
        json.dumps(
            admit_record(
                docs[0],
                owner="Herodotus",
                license="Public domain",
                access="public",
                provenance="Wikisource revid 7044570",
                admitted_by="synthetic-operator",
                admission_basis="public-domain source review",
                reviewed_at="2026-11-28",
            )
        ),
        encoding="utf-8",
    )
    result = runner.invoke(cli, ["corpus", "admit", str(admit_path), "--db-path", str(db)])
    assert result.exit_code == 0, result.output
    profile = _world_studies_profile(tmp_path)
    seed = _seed_dir(tmp_path)
    result = runner.invoke(
        cli,
        [
            "plan",
            "generate",
            "--profile",
            str(profile),
            "--format",
            "json",
            "--seed-dir",
            str(seed),
            "--slice-dir",
            str(SLICE_DIR),
            "--db-path",
            str(db),
        ],
    )
    assert result.exit_code == 0, result.output
    plan = json.loads(result.output)
    assert plan["totals"]["module_count"] == 1
    assert plan["modules"][0]["module_id"] == MODULE_ID
    db_plan_id = plan["db_plan_id"]
    result = runner.invoke(
        cli,
        [
            "plan",
            "encounter",
            str(db_plan_id),
            "--module-id",
            MODULE_ID,
            "--format",
            "json",
            "--db-path",
            str(db),
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["module_id"] == MODULE_ID
    result = runner.invoke(
        cli,
        [
            "plan",
            "encounter-complete",
            str(db_plan_id),
            "--module-id",
            MODULE_ID,
            "--response-route",
            "short_written",
            "--learner-words",
            "Synthetic response: the winds cannot be the cause.",
            "--db-path",
            str(db),
        ],
    )
    assert result.exit_code == 0, result.output
    receipt = json.loads(result.output)
    assert receipt["response_locator"].startswith("receipt:")
    chunks = storage.list_document_chunks(snapshot_id=1)
    theories = next(c for c in chunks if "three theories" in c["heading_path"])
    passage = _etesian_paragraph(theories["text"])
    span_start = theories["text"].index(passage)
    judge_path = tmp_path / "judge.json"
    judge_path.write_text(
        json.dumps(
            {
                "document_id": int(theories["document_id"]),
                "snapshot_id": 1,
                "sha256": str(theories["sha256"]),
                "chunk_index": int(theories["chunk_index"]),
                "claim": CLAIM,
                "passage": passage,
                "span_start": span_start,
                "span_end": span_start + len(passage),
                "reason": "Synthetic fixture only.",
                "reviewer": "synthetic-reviewer",
                "reviewer_status": "assistant_reviewed",
                "judgment_method": "span-grounded inspection",
                "reviewed_at": "2026-11-28",
                "judgment": "supports",
            }
        ),
        encoding="utf-8",
    )
    result = runner.invoke(cli, ["corpus", "judge", str(judge_path), "--db-path", str(db)])
    assert result.exit_code == 0, result.output
    result = runner.invoke(
        cli, ["corpus", "support", "--snapshot-id", "1", "--claim", CLAIM, "--db-path", str(db)]
    )
    assert result.exit_code == 0, result.output
    summary = json.loads(result.output)
    assert summary["status"] == "source_support_unverified"
    assert len(summary["judgments"]) == 1
