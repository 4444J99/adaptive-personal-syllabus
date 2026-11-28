"""Deterministic instructional choices, without ability inference or source rewriting."""

import hashlib
import json
from typing import Any

from .versions import ENCOUNTER_SCHEMA_VERSION

# Next instructions, keyed by the route the encounter took (the decision
# route from prior evidence). Each is a sentence, not a code: the receipt
# is read by the learner, and the justification lives in
# next_instruction_basis beside it.
_NEXT_INSTRUCTIONS = {
    "transfer_attempt": (
        "Attempt the idea in a new case; treat the transfer as untested until observed."
    ),
    "worked_explanation": (
        "Use a worked example first: identify the claim, its reason, "
        "and a case where that reason is insufficient."
    ),
    "evidence_review": (
        "Inspect the conflicting observations before choosing a harder task."
    ),
    "first_encounter": (
        "Return to this encounter; the response is recorded as a first "
        "observation and claims no mastery."
    ),
    "prerequisite_check": (
        "Inspect the prerequisites before proceeding; "
        "missing access is not a learning deficit."
    ),
    "source_unavailable": (
        "Return when the source is available; "
        "source-specific conclusions remain unverified."
    ),
}
_NO_RESPONSE_INSTRUCTION = (
    "No change: return to this encounter later; mastery stays unassessed."
)


def adapt_encounter(profile: dict[str, Any], module: dict[str, Any]) -> tuple[dict, dict]:
    purpose = profile.get("learning_purpose", "understand")
    if purpose not in ("understand", "practice", "evaluate", "enjoy"):
        raise ValueError("learning_purpose must be understand, practice, evaluate, or enjoy")
    medium = profile.get("medium", "written_or_spoken")
    if medium not in ("written_or_spoken", "page", "audio", "practice", "mixed"):
        raise ValueError("Unsupported medium")
    access = profile.get("access_conditions", {})
    prior = profile.get("prior_task_evidence", [])
    if not isinstance(access, dict) or not isinstance(prior, list):
        raise ValueError("access_conditions must be an object; prior_task_evidence must be a list")  # noqa: TRY004
    relevant = [
        e
        for e in prior
        if purpose in ("understand", "evaluate")
        and isinstance(e, dict)
        and e.get("module_id") == module["module_id"]
        and e.get("criterion") == "explain_with_counterexample"
        and isinstance(e.get("response_locator"), str)
        and e["response_locator"]
        and e.get("result") in ("demonstrated", "needs_work")
    ]
    # Conflicting observations require inspection, never optimistic score aggregation.
    results = {e["result"] for e in relevant}
    route = "first_encounter"
    if results == {"demonstrated"}:
        route = "transfer_attempt"
    elif results == {"needs_work"}:
        route = "worked_explanation"
    elif len(results) > 1:
        route = "evidence_review"
    prerequisites = module.get("prerequisites", [])
    source_available = access.get("source_available") is not False
    # A prerequisite does not erase conflicting observations of the target task.
    if prerequisites and route != "evidence_review":
        route = "prerequisite_check"
    if not source_available and route != "evidence_review":
        route = "source_unavailable"
    title = module["title"]
    tasks = {
        "understand": f"Choose one idea in {title}. Identify what it says and one case it does not explain.",
        "practice": f"Choose one procedure in {title}. Try one step and inspect its result before continuing.",
        "evaluate": f"Choose one claim about {title}. Separate its reasons from its conclusion; seek a counterexample.",
        "enjoy": f"Spend a moment with {title}. Notice a detail that interests you; no response is required.",
    }
    if not source_available:
        # This is an optional independent example, not a substitute for the source's argument.
        tasks = {
            "understand": (
                "In the example below, distinguish the recorded decline from an explanation "
                "of its cause. You may simply read the worked explanation."
            ),
            "practice": (
                "Using the example below, subtract 52 from 80, then divide the decrease by "
                "80. Compare the result with the worked explanation if you wish."
            ),
            "evaluate": (
                "In the example below, ask whether the numbers identify the cause of the "
                "decline. Consider one other change that could produce the same numbers."
            ),
            "enjoy": (
                "Read the short example below if it interests you. Notice the distinction "
                "between a change and its explanation; no response is required."
            ),
        }
    steps = [tasks[purpose]]
    if route == "transfer_attempt":
        steps.append(
            "Try the idea in a different case. Treat the transfer as untested until observed."
        )
    elif route == "worked_explanation":
        steps.append(
            "Use a worked example first: identify the claim, its reason, and a case where that reason is insufficient. You may request an explanation without assessment."
        )
    elif route == "evidence_review":
        steps.append(
            "Prior task observations disagree. Inspect those observations before choosing a harder task."
        )
    if prerequisites:
        prefix = (
            "Inspect these prerequisites before proceeding: "
            if source_available
            else "Before returning to source-specific work, inspect these prerequisites: "
        )
        steps.append(
            prefix + ", ".join(prerequisites) + ". Missing access is not a learning deficit."
        )
    phone = access.get("phone_only") is True
    if phone:
        steps.append(
            "Phone route: focus on one short passage or example. Respond in a note or a voice memo under two minutes, or just read the explanation."
        )
    if not source_available:
        steps.append(
            "The source is unavailable. The self-contained example is an independent "
            "claim-inspection activity, not instruction in this source topic; "
            "source-specific conclusions remain unverified."
        )
    if not source_available and medium == "audio":
        steps.append(
            "Use read-aloud for the short example if available, or its written version. "
            "No source recording or external page is required."
        )
    elif not source_available and medium in ("page", "mixed"):
        steps.append(
            "Keep the short example below visible. Compare its numbers with the explanation; "
            "you may also say the distinction aloud."
        )
    elif medium == "audio":
        steps.append(
            "Listen for exposition. Pause and inspect a page if notation, a diagram, code, or literary form matters."
        )
    elif medium in ("page", "mixed"):
        steps.append(
            "Keep the passage or notation visible and inspect the exact wording before evaluating it."
        )
    elif medium == "practice":
        steps.append("Perform one small reversible step, observe it, then revise your procedure.")
    decision = {
        "schema_version": ENCOUNTER_SCHEMA_VERSION,
        "purpose": purpose,
        "medium": medium,
        "route": route,
        "access_adjustment": "phone_safe" if phone else "none",
        "reason": (
            f"Purpose={purpose}; relevant task observations={len(relevant)}; "
            f"prerequisites={len(prerequisites)}; source_available={source_available}; "
            f"route={route}."
        ),
        "assessment_status": "unassessed",
    }
    encounter = {
        "authorship": "assistant_instruction",
        "status": "prepared_not_started",
        "steps": steps,
        "self_contained_example": "Recorded complaints fell from 80 to 52: 28 fewer, or 35%. This describes a decline; it does not establish what caused it.",
        "example_role": "assistant_explanation_not_source_argument",
        "example_scope": "independent_claim_inspection_not_topic_instruction",
        "source_argument": None,
        "analogy": None,
        "critique": None,
        "learner_words": None,
        "response_routes": [
            "short_written",
            "spoken_under_two_minutes",
            "worked_explanation",
            "no_response_now",
        ],
        "completion": "Understanding, enjoyment, a better question, or a useful action may end the encounter.",
    }
    return decision, encounter


def complete_encounter(
    decision: dict[str, Any],
    encounter: dict[str, Any],
    response: dict[str, Any],
) -> dict[str, Any]:
    """Build the receipt for one completed encounter.

    The receipt records an explicit response choice and the next step that
    choice justifies. It never assesses: ``assessment_status`` stays
    ``"unassessed"`` because this flow has no assessment mechanism — a
    response is an observation, not a result — so no mastery claim can be
    written by completing an encounter.

    ``response`` carries the encounter identity the caller resolved
    (neither ``decision`` nor ``encounter`` holds a ``module_id``):
    ``module_id``, ``response_route`` (one of the encounter's own
    ``response_routes``), and optional verbatim ``learner_words``.
    Learner words are copied exactly as supplied, never rewritten or
    summarized; ``no_response_now`` carries none.

    ``response_locator`` is a content address — ``receipt:<sha256>`` of
    the canonical receipt JSON — so the receipt is identical in the CLI
    echo, the ledger payload, and any artifact write. It is deliberately
    not the ledger event hash: ``Ledger.append`` computes the event hash
    from the payload at append time, so no receipt field can contain its
    own event hash before append. The event stays retrievable because
    its payload IS this receipt.
    """
    route = decision.get("route")
    if route not in _NEXT_INSTRUCTIONS:
        raise ValueError(f"Unknown decision route: {route!r}")
    module_id = response.get("module_id")
    if not isinstance(module_id, str) or not module_id:
        raise ValueError("response must carry a non-empty module_id")
    response_route = response.get("response_route")
    if response_route not in encounter.get("response_routes", []):
        raise ValueError(
            f"response_route {response_route!r} is not one of the encounter's "
            f"response_routes: {encounter.get('response_routes')}"
        )
    learner_words = response.get("learner_words")
    if learner_words is not None and not isinstance(learner_words, str):
        raise ValueError("learner_words must be text or None")
    if response_route == "no_response_now" and learner_words is not None:
        raise ValueError("no_response_now carries no learner words")

    if response_route == "no_response_now":
        # No state change: the encounter stays returnable, mastery stays
        # unassessed. The receipt records the choice itself, not a claim.
        next_instruction = _NO_RESPONSE_INSTRUCTION
    else:
        next_instruction = _NEXT_INSTRUCTIONS[route]

    receipt: dict[str, Any] = {
        "schema_version": ENCOUNTER_SCHEMA_VERSION,
        "module_id": module_id,
        "purpose": decision["purpose"],
        "route": route,
        "response_route": response_route,
        "learner_words": learner_words,
        "assessment_status": "unassessed",
        "next_instruction": next_instruction,
        "next_instruction_basis": (
            "MTR-021 acceptance + encounter.py route rules; "
            f"decision route={route} ({decision['reason']}); "
            f"response_route={response_route}."
        ),
    }
    canonical = json.dumps(receipt, sort_keys=True, separators=(",", ":"))
    receipt["response_locator"] = (
        "receipt:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    )
    return receipt
