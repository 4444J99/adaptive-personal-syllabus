"""Tests for profile-aware planning."""

from __future__ import annotations

import json
from pathlib import Path

from adaptive_personal_syllabus.corpus import CorpusIngestor
from adaptive_personal_syllabus.ledger import Ledger
from adaptive_personal_syllabus.planner import Planner
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


def _profile(path: Path, **changes: object) -> Path:
    profile_path = path / "profile.json"
    data = {
                "name": "Planner Test",
                "organs_of_interest": ["I"],
                "level": "beginner",
                "goals": ["Build a recursive system"],
                "context": {"industry": "education"},
                "completed_modules": [],
                "output_policy": {"selected_wings": []},
            }
    data.update(changes)
    profile_path.write_text(
        json.dumps(data),
        encoding="utf-8",
    )
    return profile_path


def test_planner_generate_is_deterministic_for_same_profile_and_snapshot(tmp_path: Path) -> None:
    db_path = tmp_path / "planner.db"
    storage = Storage(db_path)
    ledger = Ledger(storage)

    corpus_root = tmp_path / "corpus"
    corpus_root.mkdir()
    (corpus_root / "doc.md").write_text("# Heading\nBody", encoding="utf-8")
    CorpusIngestor(storage, ledger).ingest(corpus_root, "snapshot-a")

    planner = Planner(storage=storage, ledger=ledger, seed_dir=_seed_dir(tmp_path))
    profile_path = _profile(tmp_path)

    plan_one = planner.generate(profile_path)
    plan_two = planner.generate(profile_path)

    assert plan_one["plan_id"] == plan_two["plan_id"]
    assert [m["module_id"] for m in plan_one["modules"]] == [
        m["module_id"] for m in plan_two["modules"]
    ]
    assert plan_one["determinism_inputs"]["snapshot_id"] == plan_one["snapshot"]["id"]
    assert plan_one["determinism_inputs"]["evidence_sha256"]
    assert plan_one["modules"][0]["artifact_descriptors"] == []
    assert plan_one["output_policy"]["encounter_only"] is True
    assert plan_one["modules"][0]["source_selection"]["claim_support_status"] == "source_support_unverified"


def test_fingerprint_v2_changes_for_context_question_and_output_policy(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "planner.db")
    ledger = Ledger(storage)
    corpus_root = tmp_path / "corpus"
    corpus_root.mkdir()
    (corpus_root / "doc.md").write_text("# Foundations\nrecursive foundations", encoding="utf-8")
    CorpusIngestor(storage, ledger).ingest(corpus_root, "snapshot-a")
    seed = _seed_dir(tmp_path)
    planner = Planner(storage=storage, ledger=ledger, seed_dir=seed)
    baseline = planner.generate(_profile(tmp_path))
    changed_context = planner.generate(_profile(tmp_path, context={"industry": "music"}))
    selected_output = planner.generate(
        _profile(tmp_path, output_policy={"selected_wings": ["academic"]})
    )
    reading_data = json.loads((seed / "reading_lists.json").read_text(encoding="utf-8"))
    reading_data["entries"][0]["title"] = "Changed lesson reading"
    (seed / "reading_lists.json").write_text(json.dumps(reading_data), encoding="utf-8")
    changed_lesson = Planner(storage=storage, ledger=ledger, seed_dir=seed).generate(_profile(tmp_path))

    assert len({baseline["plan_id"], changed_context["plan_id"], selected_output["plan_id"], changed_lesson["plan_id"]}) == 4
    assert selected_output["output_policy"]["publication_authorized"] is False
    assert [w["wing_id"] for w in selected_output["modules"][0]["artifact_descriptors"]] == ["academic"]


def test_fingerprint_rejects_non_finite_profile_numbers(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "planner.db")
    ledger = Ledger(storage)
    corpus_root = tmp_path / "corpus"
    corpus_root.mkdir()
    (corpus_root / "doc.md").write_text("body", encoding="utf-8")
    CorpusIngestor(storage, ledger).ingest(corpus_root, "snapshot-a")
    planner = Planner(storage=storage, ledger=ledger, seed_dir=_seed_dir(tmp_path))
    with __import__("pytest").raises(ValueError, match="Non-finite"):
        planner.generate(_profile(tmp_path, context={"score": float("nan")}))


def test_source_selection_is_relevant_but_never_claimed_as_support(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "planner.db")
    ledger = Ledger(storage)
    corpus_root = tmp_path / "corpus"
    corpus_root.mkdir()
    (corpus_root / "relevant.md").write_text("# Foundations\nrecursive foundations", encoding="utf-8")
    (corpus_root / "irrelevant.md").write_text("# Cooking\nboil pasta", encoding="utf-8")
    CorpusIngestor(storage, ledger).ingest(corpus_root, "snapshot-a")
    plan = Planner(storage=storage, ledger=ledger, seed_dir=_seed_dir(tmp_path)).generate(_profile(tmp_path))
    candidates = plan["modules"][0]["source_selection"]["candidates"]
    assert [candidate["rel_path"] for candidate in candidates] == ["relevant.md"]
    assert all(candidate["source_support"] == "source_support_unverified" for candidate in candidates)


def test_adaptation_changes_only_for_relevant_profile_fields(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "planner.db")
    ledger = Ledger(storage)
    corpus_root = tmp_path / "corpus"
    corpus_root.mkdir()
    (corpus_root / "doc.md").write_text("foundations", encoding="utf-8")
    CorpusIngestor(storage, ledger).ingest(corpus_root, "snapshot-a")
    planner = Planner(storage=storage, ledger=ledger, seed_dir=_seed_dir(tmp_path))

    baseline = planner.generate(_profile(tmp_path))["modules"][0]["adaptation"]
    irrelevant = planner.generate(_profile(tmp_path, favorite_color="violet"))["modules"][0]["adaptation"]
    phone = planner.generate(
        _profile(tmp_path, access_conditions={"phone_only": True})
    )["modules"][0]["adaptation"]

    assert baseline == irrelevant
    assert phone["access_adjustment"] == "phone_safe"
    assert phone != baseline


def test_planner_plan_id_changes_when_snapshot_changes(tmp_path: Path) -> None:
    db_path = tmp_path / "planner.db"
    storage = Storage(db_path)
    ledger = Ledger(storage)
    planner = Planner(storage=storage, ledger=ledger, seed_dir=_seed_dir(tmp_path))
    profile_path = _profile(tmp_path)

    corpus_root_a = tmp_path / "corpus-a"
    corpus_root_a.mkdir()
    (corpus_root_a / "doc.md").write_text("# Heading\nBody A", encoding="utf-8")
    snap_a = CorpusIngestor(storage, ledger).ingest(corpus_root_a, "snapshot-a")
    plan_a = planner.generate(profile_path)

    corpus_root_b = tmp_path / "corpus-b"
    corpus_root_b.mkdir()
    (corpus_root_b / "doc.md").write_text("# Heading\nBody B", encoding="utf-8")
    snap_b = CorpusIngestor(storage, ledger).ingest(corpus_root_b, "snapshot-b")
    plan_b = planner.generate(profile_path)

    assert snap_a.snapshot_id != snap_b.snapshot_id
    assert plan_a["snapshot"]["id"] == snap_a.snapshot_id
    assert plan_b["snapshot"]["id"] == snap_b.snapshot_id
    assert plan_a["plan_id"] != plan_b["plan_id"]
