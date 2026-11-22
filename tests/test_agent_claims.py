"""Agent claim fencing (adaptive-personal-syllabus #36, MTR-010).

Exercises the four acceptance cases from #36 with synthetic tasks, plus
the registry self-check and the PR-scope gate. Every case records the
grantee, issue, grant sequence, base/head, branch, scope, expiry and
receipt the issue asks for; the receipts are asserted, not just the
verdicts, because the receipt is what a grant record cites.

Synthetic registries are built in-memory so no test depends on the live
lease file; one integration test loads the real registry and inventory
from the repo root and asserts the shipped file is consistent.
"""

from __future__ import annotations

from datetime import datetime, UTC
from pathlib import Path

from adaptive_personal_syllabus.agent_claims import (
    active_leases,
    evaluate_claim,
    inventory_class,
    load_inventory,
    load_leases,
    pr_check,
    self_check,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
MAIN_HEAD = "8dc861bcdc0d0792e0685ba577ee566b36a455a2"
NOW = datetime(2026, 11, 22, 11, 15, tzinfo=UTC)
FUTURE = "2030-01-01T00:00:00Z"
PAST = "2026-11-20T12:00:00Z"


def _registry(leases: list[dict], unowned: list[dict] | None = None) -> dict:
    return {
        "schema_version": "1.0",
        "repo": "adaptive-personal-syllabus",
        "verified_at_head": MAIN_HEAD,
        "issue": 36,
        "unowned_branches": unowned
        or [{"branch": "work/mentor/audit-truth-contract", "reason": "x"}],
        "leases": leases,
        "grant_history": [],
    }


def _lease(
    sequence: int,
    grantee: str,
    branch: str,
    scope: list[str],
    expiry: str = FUTURE,
    status: str = "active",
) -> dict:
    return {
        "sequence": sequence,
        "grantee": grantee,
        "issue": 36,
        "base": MAIN_HEAD,
        "head": MAIN_HEAD,
        "branch": branch,
        "scope": scope,
        "expiry": expiry,
        "receipt": f"synthetic lease {sequence}",
        "status": status,
    }


def _claim(
    grantee: str,
    branch: str,
    scope: list[str],
    base: str = MAIN_HEAD,
    expiry: str = FUTURE,
) -> dict:
    return {
        "grantee": grantee,
        "issue": 37,
        "branch": branch,
        "scope": scope,
        "base": base,
        "expiry": expiry,
    }


def test_simultaneous_claim_second_refused_with_receipt() -> None:
    """Acceptance case 1: two agents claim overlapping scope at once.

    The first claim holds the lease; the second is refused and its receipt
    cites the holding lease sequence and grantee.
    """
    registry = _registry(
        [_lease(1, "ranked-queue-build", "work/mentor/agent-claims", ["docs/claims/"])]
    )
    verdict = evaluate_claim(
        registry,
        _claim("steward-2", "work/mentor/other", ["docs/claims/leases.yaml"]),
        now=NOW,
        main_head=MAIN_HEAD,
    )
    assert verdict["allowed"] is False
    assert verdict["reason"] == "overlap"
    assert verdict["holding_sequence"] == 1
    assert "holding-lease=1" in verdict["receipt"]
    assert "held-by=ranked-queue-build" in verdict["receipt"]
    assert "grantee=steward-2" in verdict["receipt"]
    assert "issue=37" in verdict["receipt"]


def test_crash_expiry_frees_scope_and_records_it() -> None:
    """Acceptance case 2: a lease expires (the agent crashed, never returned).

    The scope is re-grantable and the receipt records the freed sequence.
    """
    registry = _registry(
        [
            _lease(
                1,
                "ranked-queue-build",
                "work/mentor/agent-claims",
                ["docs/claims/"],
                expiry=PAST,
            )
        ]
    )
    assert active_leases(registry, NOW) == []
    verdict = evaluate_claim(
        registry,
        _claim("steward-2", "work/mentor/other", ["docs/claims/leases.yaml"]),
        now=NOW,
        main_head=MAIN_HEAD,
    )
    assert verdict["allowed"] is True
    assert verdict["reason"] == "granted"
    assert verdict["freed_sequences"] == [1]
    assert "frees-expired-lease=1" in verdict["receipt"]


def test_partial_scope_overlap_refused() -> None:
    """Acceptance case 3: a claim overlapping only part of a live scope."""
    registry = _registry(
        [_lease(1, "ranked-queue-build", "work/mentor/agent-claims", ["docs/claims/"])]
    )
    verdict = evaluate_claim(
        registry,
        _claim(
            "steward-2",
            "work/mentor/other",
            ["docs/claims/handoff.md", "docs/adr/006-agent-claims.md"],
        ),
        now=NOW,
        main_head=MAIN_HEAD,
    )
    assert verdict["allowed"] is False
    assert verdict["reason"] == "overlap"


def test_stale_base_refused_with_rebase_receipt() -> None:
    """Acceptance case 4: a claim recorded at an old base is refused."""
    registry = _registry([])
    verdict = evaluate_claim(
        registry,
        _claim(
            "steward-2",
            "work/mentor/other",
            ["docs/claims/handoff.md"],
            base="019dfc706810a0a0ede2a921829f414c31d443f2",
        ),
        now=NOW,
        main_head=MAIN_HEAD,
    )
    assert verdict["allowed"] is False
    assert verdict["reason"] == "stale-base"
    assert f"re-base to {MAIN_HEAD}" in verdict["receipt"]


def test_same_grantee_overlap_is_an_extension() -> None:
    """The holding grantee may extend its own lease; nobody else may."""
    registry = _registry(
        [_lease(1, "ranked-queue-build", "work/mentor/agent-claims", ["docs/claims/"])]
    )
    verdict = evaluate_claim(
        registry,
        _claim("ranked-queue-build", "work/mentor/agent-claims", ["docs/claims/"]),
        now=NOW,
        main_head=MAIN_HEAD,
    )
    assert verdict["allowed"] is True
    assert verdict["reason"] == "extension"


def test_unowned_branch_refused() -> None:
    """No lease is granted over a branch the ownership table leaves unowned."""
    registry = _registry([])
    verdict = evaluate_claim(
        registry,
        _claim(
            "steward-2", "work/mentor/audit-truth-contract", ["docs/claims/"]
        ),
        now=NOW,
        main_head=MAIN_HEAD,
    )
    assert verdict["allowed"] is False
    assert verdict["reason"] == "unowned-branch"


def test_non_public_scope_refused() -> None:
    """A scope path the #33 inventory classifies review is not grantable."""
    inventory = {
        "entries": [
            {"patterns": ["docs/claims/**"], "class": "public"},
            {"patterns": ["docs/narrative-workbook/*"], "class": "review"},
        ]
    }
    registry = _registry([])
    verdict = evaluate_claim(
        registry,
        _claim("steward-2", "work/mentor/other", ["docs/narrative-workbook/x.md"]),
        now=NOW,
        main_head=MAIN_HEAD,
        inventory=inventory,
    )
    assert verdict["allowed"] is False
    assert verdict["reason"] == "non-public-scope"
    assert inventory_class("docs/claims/leases.yaml", inventory) == "public"
    assert inventory_class("README.md", inventory) is None


def test_self_check_flags_expired_active_and_overlap() -> None:
    """The registry self-check catches an expired active lease and a clash."""
    expired = _registry(
        [_lease(1, "a", "work/mentor/x", ["docs/claims/"], expiry=PAST)]
    )
    violations = self_check(expired)
    assert any("expired" in v for v in violations), violations
    clash = _registry(
        [
            _lease(1, "a", "work/mentor/x", ["docs/claims/"]),
            _lease(2, "b", "work/mentor/y", ["docs/claims/leases.yaml"]),
        ]
    )
    violations = self_check(clash)
    assert any("overlapping" in v for v in violations), violations
    clean = _registry(
        [_lease(1, "a", "work/mentor/x", ["docs/claims/"])]
    )
    assert self_check(clean) == []


def test_pr_check_fences_changed_files() -> None:
    """A PR touching another grantee's leased scope fails; its own passes."""
    registry = _registry(
        [_lease(1, "ranked-queue-build", "work/mentor/agent-claims", ["docs/claims/"])]
    )
    violations = pr_check(
        registry,
        branch="work/mentor/other",
        changed_files=["docs/claims/leases.yaml"],
    )
    assert violations, violations
    assert any("lease 1" in v for v in violations)
    own = pr_check(
        registry,
        branch="work/mentor/agent-claims",
        changed_files=["docs/claims/leases.yaml"],
        pr_base=MAIN_HEAD,
    )
    assert own == []
    unrelated = pr_check(
        registry,
        branch="work/mentor/other",
        changed_files=["src/adaptive_personal_syllabus/core.py"],
    )
    assert unrelated == []


def test_pr_check_stale_base() -> None:
    """A PR whose base moved past its lease's recorded base fails the gate."""
    registry = _registry(
        [_lease(1, "ranked-queue-build", "work/mentor/agent-claims", ["docs/claims/"])]
    )
    violations = pr_check(
        registry,
        branch="work/mentor/agent-claims",
        changed_files=["docs/claims/leases.yaml"],
        pr_base="019dfc706810a0a0ede2a921829f414c31d443f2",
    )
    assert any("stale" in v for v in violations), violations


def test_shipped_registry_is_consistent() -> None:
    """The lease file shipped in this PR passes its own self-check."""
    registry = load_leases(REPO_ROOT / "docs" / "claims" / "leases.yaml")
    inventory = load_inventory(REPO_ROOT / "docs" / "privacy-classification.yaml")
    assert registry["schema_version"] == "1.0"
    assert registry["leases"] == []
    assert self_check(registry, inventory) == []
    for entry in registry["unowned_branches"]:
        assert entry["branch"] and entry["reason"]
    history = registry["grant_history"]
    assert history and history[0]["issue"] == 36
    assert history[0]["branch"] == "work/mentor/agent-claims"
    assert history[0]["base"] == MAIN_HEAD
    for path in history[0]["scope"]:
        assert inventory_class(path, inventory) == "public", path
