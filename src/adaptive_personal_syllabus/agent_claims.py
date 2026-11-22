"""Agent claim registry and fencing (adaptive-personal-syllabus #36, MTR-010).

Before this module, the stewardship rules in AGENTS.md said claims in
comments are procedural and provide no technical locks — and nothing in
the repo checked a claim at all. This module is the check: a lease is a
record (grantee, issue, grant sequence, base/head, branch, scope, expiry,
receipt), one active lease per scope, recorded in
``docs/claims/leases.yaml``. The steward grants it; this module evaluates
it.

What is enforced, and where:

- ``evaluate_claim`` is the grant-time decision. It refuses a claim on an
  unowned branch, a claim whose scope contains a non-public path, a claim
  recorded at a stale base, and a claim whose scope overlaps an active
  lease held by another grantee; an expired holding lease frees its scope.
  Every verdict comes back as a receipt string the grant record can cite.
- ``self_check`` validates the registry itself: no overlapping active
  leases, no active lease past expiry, no lease on an unowned branch, no
  non-public scope path, no duplicate grant sequence.
- ``pr_check`` is the CI gate: it runs the self-check, then fails a PR
  whose changed files fall inside another grantee's active lease scope,
  whose own lease has expired, or whose branch base is stale relative to
  its lease. A PR with no lease of its own is unclaimed work: any overlap
  with an active lease fails it until a lease is granted.

What stays a human/steward procedure (ADR 006): granting a lease,
revoking one, settling an ownership dispute, and flipping a lease to
fulfilled/expired after its work lands. The module never grants, revokes,
or writes the registry; it only evaluates what is recorded in it.

Scope entries are repo-relative paths. An entry naming a file covers that
file; an entry ending in ``/`` covers everything under that directory.
Two scopes overlap when one entry equals, contains, or is contained by an
entry of the other scope.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LEASES_PATH = REPO_ROOT / "docs" / "claims" / "leases.yaml"
DEFAULT_INVENTORY_PATH = REPO_ROOT / "docs" / "privacy-classification.yaml"

LEASE_STATUSES = ("active", "fulfilled", "expired", "revoked")
REQUIRED_LEASE_FIELDS = (
    "sequence",
    "grantee",
    "issue",
    "base",
    "head",
    "branch",
    "scope",
    "expiry",
    "receipt",
    "status",
)


def load_leases(path: Path | str = DEFAULT_LEASES_PATH) -> dict[str, Any]:
    """The claim registry as data."""
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def load_inventory(path: Path | str = DEFAULT_INVENTORY_PATH) -> dict[str, Any]:
    """The #33 privacy-classification inventory as data."""
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def parse_time(value: str) -> datetime:
    """An ISO-8601 timestamp as an aware UTC datetime (naive reads as UTC)."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _expiry_or_none(lease: dict[str, Any]) -> datetime | None:
    """A lease's expiry, or None when it is missing or does not parse."""
    try:
        return parse_time(str(lease.get("expiry")))
    except ValueError:
        return None


def _match_parts(pattern_parts: list[str], path_parts: list[str]) -> bool:
    """Segment-wise glob: ``*`` stays inside one segment, ``**`` spans."""
    if not pattern_parts:
        return not path_parts
    head, rest = pattern_parts[0], pattern_parts[1:]
    if head == "**":
        return any(
            _match_parts(rest, path_parts[i:]) for i in range(len(path_parts) + 1)
        )
    if not path_parts:
        return False
    return fnmatch.fnmatchcase(path_parts[0], head) and _match_parts(
        rest, path_parts[1:]
    )


def inventory_match(pattern: str, path: str) -> bool:
    """Match one inventory pattern against a repo-relative path."""
    return _match_parts(pattern.split("/"), path.split("/"))


def inventory_class(path: str, inventory: dict[str, Any]) -> str | None:
    """The inventory class of a path, or None when no entry covers it."""
    classes = [
        entry["class"]
        for entry in inventory.get("entries", [])
        if any(inventory_match(pattern, path) for pattern in entry["patterns"])
    ]
    if len(classes) > 1:
        return "ambiguous"
    return classes[0] if classes else None


def _scope_entry_covers(entry: str, path: str) -> bool:
    """Whether one scope entry (file, or directory ending in ``/``) covers a path."""
    if entry.endswith("/"):
        return path.startswith(entry)
    return path == entry


def _scopes_overlap(scope_a: list[str], scope_b: list[str]) -> bool:
    """Whether any entry of one scope covers, or is covered by, the other."""
    for entry_a in scope_a:
        for entry_b in scope_b:
            if _scope_entry_covers(entry_a, entry_b) or _scope_entry_covers(
                entry_b, entry_a
            ):
                return True
    return False


def active_leases(registry: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    """Leases with status ``active`` whose expiry has not passed."""
    live = []
    for lease in registry.get("leases", []):
        if lease.get("status") != "active":
            continue
        try:
            expiry = parse_time(str(lease["expiry"]))
        except ValueError:
            continue
        if expiry > now:
            live.append(lease)
    return live


def _receipt_text(
    claim: dict[str, Any],
    verdict: str,
    holding: dict[str, Any] | None = None,
    freed: list[dict[str, Any]] | None = None,
) -> str:
    """One-line receipt: grantee, issue, base/head, branch, scope, expiry, verdict."""
    scope = ",".join(str(p) for p in claim.get("scope", []))
    text = (
        f"grantee={claim.get('grantee')} issue={claim.get('issue')} "
        f"base={claim.get('base')} branch={claim.get('branch')} "
        f"scope=[{scope}] expiry={claim.get('expiry')} verdict={verdict}"
    )
    if holding is not None:
        text += (
            f" holding-lease={holding.get('sequence')} "
            f"held-by={holding.get('grantee')}"
        )
    for lease in freed or []:
        text += f" frees-expired-lease={lease.get('sequence')}"
    return text


def evaluate_claim(
    registry: dict[str, Any],
    claim: dict[str, Any],
    *,
    now: datetime,
    main_head: str,
    inventory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Decide one claim against the registry; every verdict carries a receipt.

    Refusals, in order: unowned branch, empty scope, non-public scope path,
    stale base (the claim's base is not the current main head), an expiry
    already in the past, and overlap with another grantee's live lease. An
    expired holding lease frees its scope instead of blocking: the verdict
    is allowed and the receipt names the freed sequence. A claim from the
    grantee who already holds the overlapping lease is allowed as an
    extension of that lease.
    """
    unowned = {
        entry.get("branch")
        for entry in registry.get("unowned_branches", [])
        if entry.get("branch")
    }
    if claim.get("branch") in unowned:
        return {
            "allowed": False,
            "reason": "unowned-branch",
            "receipt": _receipt_text(claim, "refused: unowned branch"),
            "holding_sequence": None,
            "freed_sequences": [],
        }
    scope = [str(p) for p in claim.get("scope", [])]
    if not scope:
        return {
            "allowed": False,
            "reason": "empty-scope",
            "receipt": _receipt_text(claim, "refused: empty scope"),
            "holding_sequence": None,
            "freed_sequences": [],
        }
    if inventory is not None:
        for path in scope:
            klass = inventory_class(path.rstrip("/"), inventory)
            if klass != "public":
                return {
                    "allowed": False,
                    "reason": "non-public-scope",
                    "receipt": _receipt_text(
                        claim, f"refused: scope path {path} classifies {klass}"
                    ),
                    "holding_sequence": None,
                    "freed_sequences": [],
                }
    if claim.get("base") != main_head:
        return {
            "allowed": False,
            "reason": "stale-base",
            "receipt": _receipt_text(
                claim, f"refused: stale base; re-base to {main_head}"
            ),
            "holding_sequence": None,
            "freed_sequences": [],
        }
    try:
        claim_expiry = parse_time(str(claim["expiry"]))
    except ValueError:
        return {
            "allowed": False,
            "reason": "bad-expiry",
            "receipt": _receipt_text(claim, "refused: expiry does not parse"),
            "holding_sequence": None,
            "freed_sequences": [],
        }
    if claim_expiry <= now:
        return {
            "allowed": False,
            "reason": "expired-claim",
            "receipt": _receipt_text(claim, "refused: claim expiry is in the past"),
            "holding_sequence": None,
            "freed_sequences": [],
        }
    freed = [
        lease
        for lease in registry.get("leases", [])
        if lease.get("status") == "active"
        and _scopes_overlap(scope, [str(p) for p in lease.get("scope", [])])
        and (_expiry_or_none(lease) is not None)
        and _expiry_or_none(lease) <= now
    ]
    for lease in registry.get("leases", []):
        if lease.get("status") != "active":
            continue
        lease_expiry = _expiry_or_none(lease)
        if lease_expiry is None or lease_expiry <= now:
            continue
        if not _scopes_overlap(scope, [str(p) for p in lease.get("scope", [])]):
            continue
        if lease.get("grantee") == claim.get("grantee"):
            return {
                "allowed": True,
                "reason": "extension",
                "receipt": _receipt_text(
                    claim,
                    f"allowed: extends lease {lease.get('sequence')}",
                    freed=freed,
                ),
                "holding_sequence": lease.get("sequence"),
                "freed_sequences": [l.get("sequence") for l in freed],
            }
        return {
            "allowed": False,
            "reason": "overlap",
            "receipt": _receipt_text(
                claim, "refused: scope overlaps an active lease", holding=lease
            ),
            "holding_sequence": lease.get("sequence"),
            "freed_sequences": [l.get("sequence") for l in freed],
        }
    return {
        "allowed": True,
        "reason": "granted",
        "receipt": _receipt_text(claim, "allowed", freed=freed),
        "holding_sequence": None,
        "freed_sequences": [l.get("sequence") for l in freed],
    }


def self_check(
    registry: dict[str, Any], inventory: dict[str, Any] | None = None
) -> list[str]:
    """Validate the registry itself; an empty list means it is consistent."""
    violations: list[str] = []
    now = datetime.now(UTC)
    leases = registry.get("leases", [])
    sequences: list[Any] = []
    for lease in leases:
        seq = lease.get("sequence")
        sequences.append(seq)
        for field_name in REQUIRED_LEASE_FIELDS:
            if field_name not in lease:
                violations.append(f"lease {seq}: missing field {field_name}")
        if lease.get("status") not in LEASE_STATUSES:
            violations.append(
                f"lease {seq}: unknown status {lease.get('status')!r}"
            )
        try:
            expiry = parse_time(str(lease.get("expiry")))
        except ValueError:
            violations.append(f"lease {seq}: expiry does not parse")
            continue
        if lease.get("status") == "active" and expiry <= now:
            violations.append(
                f"lease {seq}: active but expired at {lease.get('expiry')} "
                "(flip to expired; the scope is already free)"
            )
        for path in lease.get("scope", []):
            if inventory is not None:
                klass = inventory_class(str(path).rstrip("/"), inventory)
                if klass != "public":
                    violations.append(
                        f"lease {seq}: scope path {path} classifies {klass}"
                    )
        unowned = {
            entry.get("branch")
            for entry in registry.get("unowned_branches", [])
            if entry.get("branch")
        }
        if lease.get("branch") in unowned:
            violations.append(
                f"lease {seq}: branch {lease.get('branch')} is unowned"
            )
    if len(sequences) != len(set(sequences)):
        violations.append("duplicate grant sequence in leases")
    for i, first in enumerate(leases):
        for second in leases[i + 1 :]:
            if (
                first.get("status") == "active"
                and second.get("status") == "active"
                and _scopes_overlap(
                    [str(p) for p in first.get("scope", [])],
                    [str(p) for p in second.get("scope", [])],
                )
            ):
                violations.append(
                    f"leases {first.get('sequence')} and "
                    f"{second.get('sequence')}: overlapping active scopes"
                )
    for entry in registry.get("unowned_branches", []):
        if not entry.get("branch") or not entry.get("reason"):
            violations.append(f"unowned branch entry without branch/reason: {entry}")
    return violations


def pr_check(
    registry: dict[str, Any],
    *,
    branch: str,
    changed_files: list[str],
    pr_base: str | None = None,
    inventory: dict[str, Any] | None = None,
) -> list[str]:
    """Gate one PR: registry consistency plus scope fencing for its files.

    Fails when the registry itself is inconsistent, when a changed file
    falls inside another grantee's active lease scope, when the PR's own
    lease has expired, or when the PR's base is stale relative to its
    lease's recorded base. A PR with no lease of its own is unclaimed
    work: any overlap with an active lease fails it until a lease is
    granted. A PR that changes nothing under any active lease passes.
    """
    violations = self_check(registry, inventory)
    now = datetime.now(UTC)
    live = active_leases(registry, now)
    own = [lease for lease in live if lease.get("branch") == branch]
    if own:
        lease = own[0]
        if pr_base is not None and pr_base != lease.get("base"):
            violations.append(
                f"lease {lease.get('sequence')}: PR base {pr_base} is stale "
                f"relative to the lease base {lease.get('base')}; re-base"
            )
    others = [lease for lease in live if lease.get("branch") != branch]
    for path in changed_files:
        for lease in others:
            scope = [str(p) for p in lease.get("scope", [])]
            if any(_scope_entry_covers(entry, path) for entry in scope):
                violations.append(
                    f"{path} falls inside active lease "
                    f"{lease.get('sequence')} (grantee "
                    f"{lease.get('grantee')}, issue "
                    f"{lease.get('issue')}); obtain a lease first"
                )
    return violations


def main(argv: list[str] | None = None) -> int:
    """CLI: --self-check, --pr-check, or --evaluate-claim (JSON file)."""
    parser = argparse.ArgumentParser(
        description="Evaluate agent claims against docs/claims/leases.yaml."
    )
    parser.add_argument("--leases", default=str(DEFAULT_LEASES_PATH))
    parser.add_argument("--inventory", default=str(DEFAULT_INVENTORY_PATH))
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--pr-check", action="store_true")
    parser.add_argument("--branch", default="")
    parser.add_argument("--changed-files", default="")
    parser.add_argument("--main-head", default="")
    parser.add_argument("--pr-base", default="")
    parser.add_argument("--evaluate-claim", default="")
    parser.add_argument("--now", default="")
    args = parser.parse_args(argv)

    registry = load_leases(args.leases)
    inventory = load_inventory(args.inventory)
    if args.self_check:
        violations = self_check(registry, inventory)
        if violations:
            print("\n".join(violations))
            return 1
        print("claim registry consistent")
        return 0
    if args.pr_check:
        changed = (
            Path(args.changed_files).read_text(encoding="utf-8").splitlines()
            if args.changed_files
            else []
        )
        changed = [line.strip() for line in changed if line.strip()]
        violations = pr_check(
            registry,
            branch=args.branch,
            changed_files=changed,
            pr_base=args.pr_base or None,
            inventory=inventory,
        )
        if violations:
            print("\n".join(violations))
            return 1
        print("claim check passed")
        return 0
    if args.evaluate_claim:
        claim = json.loads(Path(args.evaluate_claim).read_text(encoding="utf-8"))
        now = (
            parse_time(args.now)
            if args.now
            else datetime.now(UTC)
        )
        verdict = evaluate_claim(
            registry, claim, now=now, main_head=args.main_head, inventory=inventory
        )
        print(json.dumps(verdict, indent=2))
        return 0 if verdict["allowed"] else 1
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
