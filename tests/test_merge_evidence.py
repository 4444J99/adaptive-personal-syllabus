"""Merge-evidence contract (adaptive-personal-syllabus #37, MTR-011).

Exercises the six rejection reasons from the #37 plan with synthetic
evidence bundles, plus the receipt parser and the CLI in --bundle mode.
Every case asserts the verdict, the exact reason set, and the detail that
names the failing predicate — the reason is what a merge decision cites.

Synthetic bundles are built in-memory so no test depends on the live
Checks API; one integration test loads the real docs/merge-evidence.md
and asserts it names every required check and every rejection reason, so
the contract document cannot drift from the code it describes.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from adaptive_personal_syllabus.merge_evidence import (
    DESIGNATED_REVIEWERS,
    REQUIRED_CHECKS,
    _resolve_token,
    evaluate,
    parse_receipts,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
HEAD = "1111111111111111111111111111111111111111"
OLD_HEAD = "2222222222222222222222222222222222222222"
BASE = "3333333333333333333333333333333333333333"
NEW_BASE = "4444444444444444444444444444444444444444"
MAIN = "5555555555555555555555555555555555555555"
AUTHOR = "4444J99"
OTHER = "someone-else"
IMPLEMENTING_AGENT = "ranked-queue-build"
REVIEWER = DESIGNATED_REVIEWERS[0]


def _checks(head: str = HEAD, **overrides: dict) -> dict:
    """All required checks green at `head`, unless overridden."""
    checks = {
        name: {"head_sha": head, "status": "completed", "conclusion": "success"}
        for name in REQUIRED_CHECKS
    }
    checks.update(overrides)
    return checks


def _bundle(**overrides: object) -> dict:
    """A green evidence bundle at HEAD, unless overridden."""
    bundle: dict = {
        "head_sha": HEAD,
        "base_sha": BASE,
        "main_head_sha": MAIN,
        "author": AUTHOR,
        "implementing_agent": IMPLEMENTING_AGENT,
        "checks": _checks(),
        "reviews": [],
        "receipts": [],
    }
    bundle.update(overrides)
    return bundle


def _approval(user: str = OTHER, commit: str = HEAD) -> dict:
    return {
        "user": user,
        "state": "APPROVED",
        "commit_id": commit,
        "submitted_at": "2026-11-22T13:00:00Z",
    }


def _receipt(
    agent: str = REVIEWER, head: str = HEAD, verdict: str = "allow"
) -> dict:
    return {"agent": agent, "job": "pr-merge-batches", "head": head, "verdict": verdict}


def test_allow_with_github_approval_at_head() -> None:
    """Green checks + a non-author approval at the head permits a merge."""
    result = evaluate(HEAD, _bundle(reviews=[_approval()]))
    assert result["verdict"] == "allow"
    assert result["reasons"] == []


def test_allow_with_designated_receipt_at_head() -> None:
    """Green checks + a designated-reviewer's receipt at the head permits
    a merge (the batch's verification is the independent review)."""
    result = evaluate(HEAD, _bundle(receipts=[_receipt()]))
    assert result["verdict"] == "allow"
    assert result["reasons"] == []


def test_reject_missing_check() -> None:
    """A required check with no recorded run is a rejection."""
    checks = _checks()
    del checks["classification"]
    result = evaluate(HEAD, _bundle(checks=checks, reviews=[_approval()]))
    assert result["verdict"] == "reject"
    assert result["reasons"] == ["missing-check"]
    assert any("classification" in d for d in result["details"])


def test_reject_check_not_completed() -> None:
    """A required check still running is a rejection, not a pass: no
    completed successful run at the head exists yet."""
    checks = _checks(
        **{"test (3.11)": {"head_sha": HEAD, "status": "in_progress", "conclusion": None}}
    )
    result = evaluate(HEAD, _bundle(checks=checks, reviews=[_approval()]))
    assert result["verdict"] == "reject"
    assert result["reasons"] == ["missing-check"]
    assert any("not completed" in d for d in result["details"])


def test_reject_skipped_check() -> None:
    """A skipped required check is a rejection (skipped is not success)."""
    checks = _checks(
        **{"clean-checkout": {"head_sha": HEAD, "status": "completed", "conclusion": "skipped"}}
    )
    result = evaluate(HEAD, _bundle(checks=checks, reviews=[_approval()]))
    assert result["verdict"] == "reject"
    assert result["reasons"] == ["skipped-check"]


def test_reject_failed_check() -> None:
    """A failed required check is a rejection."""
    checks = _checks(
        **{"test (3.12)": {"head_sha": HEAD, "status": "completed", "conclusion": "failure"}}
    )
    result = evaluate(HEAD, _bundle(checks=checks, reviews=[_approval()]))
    assert result["verdict"] == "reject"
    assert result["reasons"] == ["failed-check"]


def test_reject_check_at_older_head() -> None:
    """A required check that ran at an older head does not bind this head."""
    checks = _checks(
        **{"Analyze Code (python)": {"head_sha": OLD_HEAD, "status": "completed", "conclusion": "success"}}
    )
    result = evaluate(HEAD, _bundle(checks=checks, reviews=[_approval()]))
    assert result["verdict"] == "reject"
    assert result["reasons"] == ["stale-head"]


def test_reject_approval_at_older_head() -> None:
    """An approval recorded at an older head is rejected after any new head."""
    result = evaluate(HEAD, _bundle(reviews=[_approval(commit=OLD_HEAD)]))
    assert result["verdict"] == "reject"
    assert result["reasons"] == ["stale-head"]
    assert any("no approval binds" in d for d in result["details"])


def test_reject_no_approval_at_all() -> None:
    """Green checks with no approval and no receipt do not permit a merge:
    the contract requires an independent review at the exact head."""
    result = evaluate(HEAD, _bundle())
    assert result["verdict"] == "reject"
    assert result["reasons"] == ["stale-head"]


def test_reject_self_approval() -> None:
    """Author == approver is rejected, even at the exact head."""
    result = evaluate(HEAD, _bundle(reviews=[_approval(user=AUTHOR)]))
    assert result["verdict"] == "reject"
    assert result["reasons"] == ["self-approval"]


def test_reject_receipt_at_older_head() -> None:
    """A designated receipt recorded at an older head does not bind this head."""
    result = evaluate(HEAD, _bundle(receipts=[_receipt(head=OLD_HEAD)]))
    assert result["verdict"] == "reject"
    assert result["reasons"] == ["stale-head"]


def test_reject_receipt_from_implementing_agent() -> None:
    """A receipt from the implementing agent is self-approval, not an
    independent review — even when the agent is a designated reviewer job
    (the batch opening a PR and then receipting it would approve itself)."""
    result = evaluate(
        HEAD,
        _bundle(implementing_agent=REVIEWER, receipts=[_receipt()]),
    )
    assert result["verdict"] == "reject"
    assert result["reasons"] == ["self-approval"]


def test_reject_receipt_with_reject_verdict() -> None:
    """A receipt that itself says reject is not an approval."""
    result = evaluate(HEAD, _bundle(receipts=[_receipt(verdict="reject")]))
    assert result["verdict"] == "reject"
    assert result["reasons"] == ["stale-head"]


def test_reject_receipt_from_undesignated_agent() -> None:
    """A receipt from an agent outside the designated-reviewer list is not
    an approval: no producer is trusted by default, each must be named."""
    result = evaluate(HEAD, _bundle(receipts=[_receipt(agent="some-other-job")]))
    assert result["verdict"] == "reject"
    assert result["reasons"] == ["stale-head"]


def test_reject_stored_bundle_base_moved() -> None:
    """A stored bundle is invalidated when main moved under the head since
    the evidence was recorded (base_sha differs from live merge-base)."""
    live = {"base_sha": NEW_BASE, "main_head_sha": MAIN, "head_is_ancestor": True}
    result = evaluate(HEAD, _bundle(reviews=[_approval()]), live=live)
    assert result["verdict"] == "reject"
    assert result["reasons"] == ["invalidated-base"]


def test_reject_stored_bundle_head_rewritten() -> None:
    """A stored bundle is invalidated when its head is no longer an
    ancestor of the live head (force-push rewrite)."""
    live = {"base_sha": BASE, "main_head_sha": MAIN, "head_is_ancestor": False}
    result = evaluate(HEAD, _bundle(reviews=[_approval()]), live=live)
    assert result["verdict"] == "reject"
    assert result["reasons"] == ["invalidated-base"]


def test_reject_bundle_for_another_head() -> None:
    """Evaluating a bundle recorded for a different head is a rejection."""
    result = evaluate(HEAD, _bundle(head_sha=OLD_HEAD, reviews=[_approval()]))
    assert result["verdict"] == "reject"
    assert result["reasons"] == ["stale-head"]


def test_latest_review_per_user_wins() -> None:
    """A later CHANGES_REQUESTED supersedes an earlier APPROVED from the
    same reviewer: the latest review per user decides."""
    reviews = [
        _approval(),
        {
            "user": OTHER,
            "state": "CHANGES_REQUESTED",
            "commit_id": HEAD,
            "submitted_at": "2026-11-22T14:00:00Z",
        },
    ]
    result = evaluate(HEAD, _bundle(reviews=reviews))
    assert result["verdict"] == "reject"
    assert result["reasons"] == ["stale-head"]


def test_latest_check_run_in_progress_supersedes_completed() -> None:
    """A re-run in progress supersedes an older completed run: the check
    is not yet decided, so the evaluator must not credit the old success."""
    from adaptive_personal_syllabus.merge_evidence import _latest_check_runs

    runs = [
        {
            "name": "test (3.11)",
            "head_sha": HEAD,
            "status": "completed",
            "conclusion": "success",
            "started_at": "2026-11-22T11:00:00Z",
            "completed_at": "2026-11-22T11:05:00Z",
        },
        {
            "name": "test (3.11)",
            "head_sha": HEAD,
            "status": "in_progress",
            "conclusion": None,
            "started_at": "2026-11-22T12:00:00Z",
            "completed_at": None,
        },
    ]
    latest = _latest_check_runs(runs, HEAD)
    assert latest["test (3.11)"]["status"] == "in_progress"
    result = evaluate(
        HEAD,
        _bundle(
            checks={**_checks(), **latest},
            reviews=[_approval()],
        ),
    )
    assert result["verdict"] == "reject"
    assert result["reasons"] == ["missing-check"]


def test_receipt_parser_accepts_marked_json_block() -> None:
    """A receipt is a marker line plus a fenced JSON block in a PR comment."""
    body = (
        "verified this head\n\n<!-- merge-evidence-receipt -->\n"
        '```json\n{"agent": "pr-merge-batches", "job": "pr-merge-batches", '
        '"head": "' + HEAD + '", "verdict": "allow"}\n```\n'
    )
    receipts = parse_receipts([{"body": body}])
    assert receipts == [_receipt()]


def test_receipt_parser_ignores_malformed_blocks() -> None:
    """A malformed receipt block is ignored, never trusted."""
    bodies = [
        "<!-- merge-evidence-receipt -->\n```json\n{not json\n```\n",
        "<!-- merge-evidence-receipt -->\nno fenced block here\n",
        "no marker at all\n```json\n{\"agent\": \"pr-merge-batches\"}\n```\n",
    ]
    assert parse_receipts([{"body": b} for b in bodies]) == []


def test_contract_doc_names_required_checks_and_reasons() -> None:
    """docs/merge-evidence.md must name every required check and every
    rejection reason, so the document cannot drift from the code."""
    from adaptive_personal_syllabus.merge_evidence import REASONS

    doc = (REPO_ROOT / "docs" / "merge-evidence.md").read_text(encoding="utf-8")
    for name in REQUIRED_CHECKS:
        assert name in doc, f"contract doc does not name required check: {name}"
    for reason in REASONS:
        assert reason in doc, f"contract doc does not name reason: {reason}"


def test_resolve_token_prefers_explicit_token(tmp_path: Path) -> None:
    """--token wins over --token-file; a token file is read stripped; with
    neither, the token is empty (the CLI then reports that it needs one).
    The token is never read from the environment: the public-surface
    contract forbids `os.environ` in src modules."""
    token_file = tmp_path / "token"
    token_file.write_text("  file-token\n", encoding="utf-8")
    assert _resolve_token("explicit", str(token_file)) == "explicit"
    assert _resolve_token("", str(token_file)) == "file-token"
    assert _resolve_token("", "") == ""


def test_cli_bundle_mode_with_token_file(tmp_path: Path) -> None:
    """The CLI accepts --token-file end to end: with a token file present
    it evaluates the stored bundle instead of erroring on a missing token."""
    module = "adaptive_personal_syllabus.merge_evidence"
    token_file = tmp_path / "token"
    token_file.write_text("dummy-token\n", encoding="utf-8")
    bundle_path = tmp_path / "allow.json"
    bundle_path.write_text(json.dumps(_bundle(reviews=[_approval()])), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", module, "--bundle", str(bundle_path), "--head", HEAD,
         "--token-file", str(token_file)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"},
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["verdict"] == "allow"


def test_cli_bundle_mode_allow_and_reject(tmp_path: Path) -> None:
    """The CLI evaluates a stored bundle file: exit 0 on allow, 1 on reject,
    verdict JSON on stdout in both cases."""
    module = "adaptive_personal_syllabus.merge_evidence"
    allow_path = tmp_path / "allow.json"
    allow_path.write_text(json.dumps(_bundle(reviews=[_approval()])), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", module, "--bundle", str(allow_path), "--head", HEAD],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"},
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["verdict"] == "allow"

    reject_path = tmp_path / "reject.json"
    reject_path.write_text(json.dumps(_bundle()), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", module, "--bundle", str(reject_path), "--head", HEAD],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"},
        check=False,
    )
    assert proc.returncode == 1, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["verdict"] == "reject"
    assert payload["reasons"] == ["stale-head"]
