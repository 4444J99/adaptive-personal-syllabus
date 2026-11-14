"""Inspect learner-facing routes and their bounded use of supplied task evidence."""

from __future__ import annotations

import copy
import json

import pytest

from adaptive_personal_syllabus.encounter import adapt_encounter


@pytest.fixture
def module():
    return {
        "module_id": "synthetic-claims",
        "title": "Inspecting claims",
        "questions": ["What would disprove this claim?"],
        "prerequisites": [],
    }


def observation(module, result="demonstrated", **changes):
    record = {
        "module_id": module["module_id"],
        "criterion": "explain_with_counterexample",
        "response_locator": "synthetic:response",
        "result": result,
    }
    record.update(changes)
    return record


def test_conflicting_observations_remain_visible_with_prerequisites(module):
    module["prerequisites"] = ["synthetic-prerequisite"]
    decision, encounter = adapt_encounter(
        {
            "prior_task_evidence": [
                observation(module),
                observation(module, "needs_work"),
            ],
        },
        module,
    )
    assert decision["route"] == "evidence_review"
    assert any("observations disagree" in step for step in encounter["steps"])
    assert any("synthetic-prerequisite" in step for step in encounter["steps"])
    assert decision["assessment_status"] == "unassessed"


@pytest.mark.parametrize("medium", ["page", "mixed", "audio", "practice"])
def test_unavailable_source_uses_an_accessible_activity(module, medium):
    decision, encounter = adapt_encounter(
        {
            "medium": medium,
            "access_conditions": {"phone_only": True, "source_available": False},
        },
        module,
    )
    instructions = " ".join(encounter["steps"])
    assert "example" in encounter["steps"][0]
    assert "Choose one idea in Inspecting claims" not in instructions
    assert "Keep the passage or notation visible" not in instructions
    assert "Pause and inspect a page" not in instructions
    assert "source-specific conclusions remain unverified" in instructions
    assert "under two minutes" in instructions
    assert decision["assessment_status"] == "unassessed"


def test_each_selected_purpose_changes_the_actual_available_example_task(module):
    starts = []
    for purpose in ("understand", "practice", "evaluate", "enjoy"):
        _, encounter = adapt_encounter(
            {"learning_purpose": purpose, "access_conditions": {"source_available": False}},
            module,
        )
        starts.append(encounter["steps"][0])
    assert len(set(starts)) == 4
    assert "80" in starts[1] and "52" in starts[1]
    assert "cause" in starts[2]
    assert "no response" in starts[3]


@pytest.mark.parametrize("purpose", ["practice", "enjoy"])
def test_argument_evidence_does_not_force_a_different_activity(module, purpose):
    baseline = adapt_encounter({"learning_purpose": purpose}, module)
    observed = adapt_encounter(
        {"learning_purpose": purpose, "prior_task_evidence": [observation(module)]}, module
    )
    assert observed == baseline


@pytest.mark.parametrize("result", ["demonstrated", "needs_work"])
def test_matching_evidence_changes_instruction_without_claiming_new_performance(module, result):
    _, baseline = adapt_encounter({}, module)
    decision, encounter = adapt_encounter(
        {"prior_task_evidence": [observation(module, result)]}, module
    )
    assert encounter["steps"] != baseline["steps"]
    assert decision["assessment_status"] == "unassessed"
    assert encounter["status"] == "prepared_not_started"
    assert encounter["learner_words"] is None
    assert encounter["response_routes"] == baseline["response_routes"]


@pytest.mark.parametrize(
    "change",
    [
        {"favorite_color": "violet"},
        {"reading_history": ["A book already read"]},
        {"context": {"private_circumstances": "PRIVATE_MARKER"}},
        {"level": "advanced"},
        {"completed_modules": ["synthetic-prerequisite"]},
        {"prior_task_evidence": [{"module_id": "unrelated", "result": "demonstrated"}]},
    ],
)
def test_irrelevant_profile_change_leaves_instruction_unchanged(module, change):
    before = copy.deepcopy((change, module))
    assert adapt_encounter(change, module) == adapt_encounter({}, module)
    assert (change, module) == before


def test_prerequisite_evidence_is_not_inferred_from_target_or_completed_reading(module):
    module["prerequisites"] = ["synthetic-prerequisite"]
    decision, encounter = adapt_encounter(
        {
            "prior_task_evidence": [observation(module)],
            "reading_history": ["synthetic-prerequisite"],
            "completed_modules": ["synthetic-prerequisite"],
        },
        module,
    )
    assert decision["route"] == "prerequisite_check"
    assert any("synthetic-prerequisite" in step for step in encounter["steps"])


def test_unavailable_topic_evidence_does_not_become_a_transfer_claim_about_fallback(module):
    decision, encounter = adapt_encounter(
        {
            "prior_task_evidence": [observation(module)],
            "access_conditions": {"source_available": False},
        },
        module,
    )
    assert decision["route"] == "source_unavailable"
    assert not any("Treat the transfer" in step for step in encounter["steps"])
    assert encounter["example_scope"] == "independent_claim_inspection_not_topic_instruction"


def test_source_absence_does_not_erase_conflicting_task_observations(module):
    module["prerequisites"] = ["synthetic-prerequisite"]
    decision, encounter = adapt_encounter(
        {
            "prior_task_evidence": [observation(module), observation(module, "needs_work")],
            "access_conditions": {"source_available": False},
        },
        module,
    )
    assert decision["route"] == "evidence_review"
    assert any("observations disagree" in step for step in encounter["steps"])
    assert any("Before returning to source-specific work" in step for step in encounter["steps"])
    assert encounter["status"] == "prepared_not_started"


def test_instruction_roles_do_not_rewrite_source_or_learner_words(module):
    _, encounter = adapt_encounter(
        {
            "prior_task_evidence": [
                observation(module, exact_learner_words="PRIVATE_LEARNER_WORDS")
            ],
            "context": {"secret": "PRIVATE_CONTEXT"},
        },
        module,
    )
    serialized = json.dumps(encounter)
    assert "PRIVATE_" not in serialized
    assert encounter["authorship"] == "assistant_instruction"
    assert encounter["example_role"] == "assistant_explanation_not_source_argument"
    for role in ("source_argument", "analogy", "critique", "learner_words"):
        assert encounter[role] is None
    assert "worked_explanation" in encounter["response_routes"]
    assert "no_response_now" in encounter["response_routes"]


def test_basic_generation_uses_no_credentials_and_roundtrips_actual_instruction(tmp_path, monkeypatch):
    from adaptive_personal_syllabus.corpus import CorpusIngestor
    from adaptive_personal_syllabus.ledger import Ledger
    from adaptive_personal_syllabus.planner import Planner
    from adaptive_personal_syllabus.storage import Storage
    from tests.test_planner import _profile, _seed_dir

    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "fixture.md").write_text("# Foundations\nA synthetic passage.", encoding="utf-8")
    storage = Storage(tmp_path / "synthetic.db")
    ledger = Ledger(storage)
    CorpusIngestor(storage, ledger).ingest(root, "synthetic")
    planner = Planner(storage, ledger, _seed_dir(tmp_path))
    plan = planner.generate(
        _profile(
            tmp_path,
            level="unassessed",
            learning_purpose="practice",
            access_conditions={"phone_only": True, "source_available": False},
        )
    )
    persisted = storage.get_plan(plan["db_plan_id"])
    assert persisted["modules"][0]["encounter"] == plan["modules"][0]["encounter"]
    assert "80" in plan["modules"][0]["encounter"]["steps"][0]
    assert plan["profile"]["level"] == "unassessed"
    assert plan["output_policy"]["publication_authorized"] is False
