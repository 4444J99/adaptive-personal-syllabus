"""Inspect learner-facing routes and their bounded use of supplied task evidence."""

from __future__ import annotations

import copy
import json

import pytest
from click.testing import CliRunner

from adaptive_personal_syllabus.core import cli
from adaptive_personal_syllabus.encounter import adapt_encounter, complete_encounter


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


# --- #51 (MTR-021): encounter completion receipts ---------------------------
#
# A receipt records an explicit response choice and the next step that
# choice justifies. It never assesses: assessment_status stays
# "unassessed" because this flow has no assessment mechanism.


def _response(module, route, words=None):
    return {"module_id": module["module_id"], "response_route": route, "learner_words": words}


@pytest.mark.parametrize(
    "route",
    ["short_written", "spoken_under_two_minutes", "worked_explanation", "no_response_now"],
)
def test_receipt_for_each_response_route(module, route):
    decision, encounter = adapt_encounter({}, module)
    receipt = complete_encounter(decision, encounter, _response(module, route))
    assert receipt["schema_version"] == "1.2"
    assert receipt["module_id"] == module["module_id"]
    assert receipt["purpose"] == "understand"
    assert receipt["route"] == "first_encounter"
    assert receipt["response_route"] == route
    assert receipt["learner_words"] is None
    assert receipt["assessment_status"] == "unassessed"
    assert receipt["next_instruction"]
    assert "MTR-021" in receipt["next_instruction_basis"]
    assert decision["reason"] in receipt["next_instruction_basis"]
    assert receipt["response_locator"].startswith("receipt:")
    assert len(receipt["response_locator"]) == len("receipt:") + 64


def test_no_response_now_records_choice_without_mastery_claim(module):
    decision, encounter = adapt_encounter({}, module)
    receipt = complete_encounter(decision, encounter, _response(module, "no_response_now"))
    assert receipt["assessment_status"] == "unassessed"
    assert receipt["learner_words"] is None
    assert receipt["next_instruction"].startswith("No change:")
    assert "mastery stays unassessed" in receipt["next_instruction"]
    # A no-response completion carries no learner words at all.
    with pytest.raises(ValueError, match="no_response_now carries no learner words"):
        complete_encounter(
            decision, encounter, _response(module, "no_response_now", "I did respond")
        )


def test_authentic_response_is_verbatim_and_located(module):
    decision, encounter = adapt_encounter({}, module)
    words = "The decline is 28 fewer — but WHY it fell is Not in the numbers."
    receipt = complete_encounter(decision, encounter, _response(module, "short_written", words))
    assert receipt["learner_words"] == words
    assert receipt["response_locator"]
    # The receipt is deterministic: the same completion has the same locator.
    again = complete_encounter(decision, encounter, _response(module, "short_written", words))
    assert again == receipt
    assert again["response_locator"] == receipt["response_locator"]
    # Different words are a different receipt with a different locator.
    other = complete_encounter(decision, encounter, _response(module, "short_written", "other words"))
    assert other["response_locator"] != receipt["response_locator"]


@pytest.mark.parametrize(
    ("result", "instruction_start"),
    [
        ("demonstrated", "Attempt the idea in a new case"),
        ("needs_work", "Use a worked example first"),
    ],
)
def test_prior_result_routes_receipt_to_its_next_step(module, result, instruction_start):
    decision, encounter = adapt_encounter(
        {"prior_task_evidence": [observation(module, result)]}, module
    )
    receipt = complete_encounter(decision, encounter, _response(module, "short_written"))
    assert receipt["next_instruction"].startswith(instruction_start)
    assert f"route={decision['route']}" in receipt["next_instruction_basis"]


def test_conflicting_observations_route_receipt_to_evidence_review(module):
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
    receipt = complete_encounter(decision, encounter, _response(module, "short_written"))
    assert receipt["next_instruction"].startswith("Inspect the conflicting observations")
    assert "relevant task observations=2" in receipt["next_instruction_basis"]


def test_unknown_routes_are_rejected(module):
    decision, encounter = adapt_encounter({}, module)
    with pytest.raises(ValueError, match="not one of the encounter's response_routes"):
        complete_encounter(decision, encounter, _response(module, "shouted_aloud"))
    with pytest.raises(ValueError, match="Unknown decision route"):
        complete_encounter({**decision, "route": "teleport"}, encounter, _response(module, "short_written"))
    with pytest.raises(ValueError, match="non-empty module_id"):
        complete_encounter(decision, encounter, {"response_route": "short_written"})


def _synthetic_plan(tmp_path, monkeypatch):
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
    plan = planner.generate(_profile(tmp_path, level="unassessed", learning_purpose="understand"))
    return storage, ledger, plan


def test_receipt_round_trips_and_matches_ledger_payload(tmp_path, monkeypatch):
    from adaptive_personal_syllabus.ledger import Ledger

    storage, ledger, plan = _synthetic_plan(tmp_path, monkeypatch)
    module = plan["modules"][0]
    receipt = complete_encounter(
        module["adaptation"],
        module["encounter"],
        _response(module, "short_written", "A synthetic first response."),
    )
    assert json.loads(json.dumps(receipt)) == receipt
    event = ledger.append("encounter.receipt", receipt)
    assert event.event_hash
    rows = list(storage.iter_ledger_events())
    stored = [json.loads(row["payload_json"]) for row in rows if row["event_type"] == "encounter.receipt"]
    assert stored == [receipt]
    ok, errors, count = Ledger(storage).verify_chain()
    assert ok, errors
    assert count == len(rows)


def test_cli_encounter_complete_appends_one_receipt_and_echoes_it(tmp_path, monkeypatch):
    from adaptive_personal_syllabus.ledger import Ledger

    storage, _ledger, plan = _synthetic_plan(tmp_path, monkeypatch)
    plan_id = plan["db_plan_id"]
    db = str(tmp_path / "synthetic.db")
    runner = CliRunner()

    before = len(list(storage.iter_ledger_events()))
    no_response = runner.invoke(
        cli, ["plan", "encounter-complete", str(plan_id), "--response-route", "no_response_now", "--db-path", db]
    )
    assert no_response.exit_code == 0, no_response.output
    echoed = json.loads(no_response.output)
    assert echoed["response_route"] == "no_response_now"
    assert echoed["assessment_status"] == "unassessed"
    after_first = list(storage.iter_ledger_events())
    assert len(after_first) == before + 1
    receipts = [r for r in after_first if r["event_type"] == "encounter.receipt"]
    assert len(receipts) == 1
    assert json.loads(receipts[0]["payload_json"]) == echoed

    words = "The numbers describe a decline; they do not name its cause."
    written = runner.invoke(
        cli,
        ["plan", "encounter-complete", str(plan_id), "--response-route", "short_written",
         "--learner-words", words, "--db-path", db],
    )
    assert written.exit_code == 0, written.output
    echoed_written = json.loads(written.output)
    assert echoed_written["learner_words"] == words
    assert echoed_written["next_instruction"].startswith("Return to this encounter")
    rows = list(storage.iter_ledger_events())
    assert len(rows) == before + 2
    assert len([r for r in rows if r["event_type"] == "encounter.receipt"]) == 2
    ok, errors, _ = Ledger(storage).verify_chain()
    assert ok, errors


def test_cli_plan_encounter_still_records_nothing(tmp_path, monkeypatch):
    storage, _ledger, plan = _synthetic_plan(tmp_path, monkeypatch)
    plan_id = plan["db_plan_id"]
    db = str(tmp_path / "synthetic.db")
    runner = CliRunner()
    before = len(list(storage.iter_ledger_events()))
    for route in ("no_response_now", "short_written"):
        result = runner.invoke(
            cli, ["plan", "encounter", str(plan_id), "--route", route, "--format", "json", "--db-path", db]
        )
        assert result.exit_code == 0, result.output
    assert len(list(storage.iter_ledger_events())) == before
