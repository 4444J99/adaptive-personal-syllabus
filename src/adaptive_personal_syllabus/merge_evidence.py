"""Merge-evidence contract (adaptive-personal-syllabus #37, MTR-011).

Before this module, the merge policy lived only as prose in BRANCHES.md
("Reviewed, bounded PRs whose evidence matches head", "New head
invalidates old head-specific evidence") while main reported
``protected: false`` and ``rulesets: []`` — nothing in the GitHub settings
layer required a check, a review, or anything else before a merge, and a
merge could ignore every green check and still land. This module is the
contract as code: it evaluates, for one head SHA and one evidence bundle,
whether the evidence permits a merge.

The contract, in full, is docs/merge-evidence.md; the decision behind it
is ADR 007. This module implements it and nothing else:

- ``evaluate`` is pure: a head SHA, an evidence bundle, and (when
  evaluating a stored bundle) the live base state. It returns a verdict
  (``allow`` / ``reject``) with one reason per failing predicate, from
  exactly six reasons: ``stale-head``, ``missing-check``,
  ``skipped-check``, ``failed-check``, ``self-approval``,
  ``invalidated-base``.
- ``fetch_evidence`` is the I/O boundary: it reads the PR, its check
  runs, its reviews, and its receipt comments from the Checks/Reviews
  API at the given head and builds the bundle ``evaluate`` consumes.
  It never writes anything and never changes a setting.
- ``parse_receipts`` reads review receipts out of PR comments. A receipt
  is how the designated independent reviewer (the pr-merge-batches job)
  records that it verified the evidence at a head; it is the review
  identity the Checks API cannot carry, because all loop work
  authenticates as one login.

What stays a human/steward procedure (ADR 007): enabling the ruleset or
branch protection on main that names the required checks, and granting
the leases the claim registry fences. The module never changes a
setting; it only evaluates what is recorded. Until the settings half
lands, the merge-evidence workflow is advisory: it reports the verdict
but the settings layer cannot enforce it, and the contract document
says so.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REQUIRED_CHECKS: tuple[str, ...] = (
    "test (3.11)",
    "test (3.12)",
    "Analyze Code (python)",
    "Secret Pattern Detection",
    "classification",
    "clean-checkout",
)

REASONS: tuple[str, ...] = (
    "stale-head",
    "missing-check",
    "skipped-check",
    "failed-check",
    "self-approval",
    "invalidated-base",
)

DESIGNATED_REVIEWERS: tuple[str, ...] = ("pr-merge-batches",)

RECEIPT_MARKER = "<!-- merge-evidence-receipt -->"
_RECEIPT_BLOCK_RE = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL)

API_BASE = "https://api.github.com"


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    """First occurrence wins; the verdict cites each reason once."""
    seen: set[str] = set()
    kept: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            kept.append(item)
    return kept


def evaluate(
    head_sha: str, bundle: dict[str, Any], live: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Decide whether the evidence bundle permits merging `head_sha`.

    `bundle` carries the evidence recorded at one head: ``head_sha``,
    ``base_sha`` (the merge-base of main and the head at evidence time),
    ``main_head_sha``, ``author`` (the PR author's login),
    ``implementing_agent`` (the lease grantee for the PR branch, or None
    when no lease names the branch), ``checks`` (required check name ->
    ``{head_sha, status, conclusion}``), ``reviews`` (``{user, state,
    commit_id, submitted_at}``), and ``receipts`` (``{agent, job, head,
    verdict}``).

    `live`, when given, is the current base state for evaluating a
    *stored* bundle: ``base_sha`` (current merge-base), ``main_head_sha``,
    ``head_is_ancestor`` (whether the bundle head is still an ancestor
    of the live head). A live evaluation builds its bundle from current
    state, so it passes ``live=None`` and the base predicates are
    vacuous there; the stored-bundle path is what exercises them.

    One reason per failing predicate. A check run at another head is
    ``stale-head``; a check with no completed run is ``missing-check``
    (a run still in progress has produced no completed evidence yet); a
    ``skipped`` conclusion is ``skipped-check``; any other non-success
    conclusion is ``failed-check``. An approval counts only when it binds
    this head: a GitHub approval by a login other than the author's, or
    a designated reviewer's receipt at this head. An approval by the
    author at this head is ``self-approval``. No approval binding the
    head is ``stale-head`` (the evidence does not bind this head) unless
    a self-approval was recorded, which explains the failure on its own.
    A stored bundle whose base moved, or whose head was rewritten, is
    ``invalidated-base``.
    """
    reasons: list[str] = []
    details: list[str] = []
    self_approval = False

    # 1. The bundle itself must be recorded for this head.
    bundle_head = bundle.get("head_sha")
    if bundle_head != head_sha:
        reasons.append("stale-head")
        details.append(
            f"evidence bundle records head {bundle_head}, evaluating {head_sha}"
        )

    # 2. Every required check: present, completed, successful, at this head.
    checks = bundle.get("checks", {})
    for name in REQUIRED_CHECKS:
        run = checks.get(name)
        if run is None:
            reasons.append("missing-check")
            details.append(f"{name}: no run recorded")
            continue
        if run.get("status") != "completed":
            reasons.append("missing-check")
            details.append(f"{name}: run not completed ({run.get('status')})")
            continue
        if run.get("head_sha") != head_sha:
            reasons.append("stale-head")
            details.append(
                f"{name}: run at {run.get('head_sha')}, not {head_sha}"
            )
            continue
        conclusion = run.get("conclusion")
        if conclusion == "skipped":
            reasons.append("skipped-check")
            details.append(f"{name}: conclusion is skipped, not success")
        elif conclusion != "success":
            reasons.append("failed-check")
            details.append(f"{name}: conclusion is {conclusion}, not success")

    # 3. Approval: an independent review binding this head.
    author = bundle.get("author")
    latest: dict[str, dict[str, Any]] = {}
    for review in bundle.get("reviews", []):
        user = review.get("user")
        if user is None:
            continue
        previous = latest.get(user)
        if previous is None or (review.get("submitted_at") or "") >= (
            previous.get("submitted_at") or ""
        ):
            latest[user] = review
    approval_ok = False
    for user, review in latest.items():
        if review.get("state") != "APPROVED":
            continue
        if review.get("commit_id") != head_sha:
            continue
        if user == author:
            self_approval = True
            details.append(f"author {author} approved this head (self-approval)")
        else:
            approval_ok = True
    implementing_agent = bundle.get("implementing_agent")
    for receipt in bundle.get("receipts", []):
        agent = receipt.get("agent")
        if agent not in DESIGNATED_REVIEWERS:
            continue
        if receipt.get("verdict") != "allow":
            continue
        if receipt.get("head") != head_sha:
            reasons.append("stale-head")
            details.append(
                f"receipt from {agent} binds older head {receipt.get('head')}"
            )
            continue
        if implementing_agent is not None and agent == implementing_agent:
            self_approval = True
            details.append(
                f"receipt from implementing agent {agent} (self-approval)"
            )
            continue
        approval_ok = True
    if self_approval and "self-approval" not in reasons:
        reasons.append("self-approval")
    if not approval_ok and not self_approval:
        reasons.append("stale-head")
        details.append("no approval binds this head")

    # 4. Stored-bundle base predicates: main moved, or the head rewritten.
    if live is not None:
        live_base = live.get("base_sha")
        bundle_base = bundle.get("base_sha")
        if (
            live_base is not None
            and bundle_base is not None
            and live_base != bundle_base
        ):
            reasons.append("invalidated-base")
            details.append(
                f"base moved under the head: evidence recorded at base "
                f"{bundle_base}, live merge-base is {live_base}"
            )
        if live.get("head_is_ancestor") is False:
            reasons.append("invalidated-base")
            details.append(
                f"head {bundle_head} is no longer an ancestor of the live "
                "head (history rewritten)"
            )

    ordered = _dedupe_preserve_order(reasons)
    return {
        "verdict": "allow" if not ordered else "reject",
        "reasons": ordered,
        "details": details,
    }


def parse_receipts(comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Review receipts out of PR comment bodies.

    A receipt is the marker line ``<!-- merge-evidence-receipt -->``
    followed by a fenced JSON block with ``agent``, ``job``, ``head`` and
    ``verdict``. A comment without the marker, or with a block that does
    not parse as a JSON object, contributes nothing: a malformed receipt
    is ignored, never trusted.
    """
    receipts: list[dict[str, Any]] = []
    for comment in comments:
        body = comment.get("body") or ""
        if RECEIPT_MARKER not in body:
            continue
        tail = body.split(RECEIPT_MARKER, 1)[1]
        match = _RECEIPT_BLOCK_RE.search(tail)
        if match is None:
            continue
        try:
            parsed = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            receipts.append(parsed)
    return receipts


def _api_get(url: str, token: str) -> Any:
    """One authenticated GitHub API GET; raises on transport failure."""
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise RuntimeError(
            f"GitHub API GET {url} failed with {error.code}"
        ) from error


def _latest_check_runs(
    runs: list[dict[str, Any]], head_sha: str
) -> dict[str, dict[str, Any]]:
    """Latest run per required check name, by started_at.

    The newest-started run wins, whatever its state: a re-run in
    progress supersedes an older completed run, so the evaluator sees
    the check as not yet decided (missing-check) instead of crediting
    stale evidence from the earlier run.
    """
    latest: dict[str, dict[str, Any]] = {}
    for run in runs:
        name = run.get("name")
        if name not in REQUIRED_CHECKS:
            continue
        previous = latest.get(name)
        if previous is None or (run.get("started_at") or "") >= (
            previous.get("started_at") or ""
        ):
            latest[name] = {
                "head_sha": run.get("head_sha", head_sha),
                "status": run.get("status"),
                "conclusion": run.get("conclusion"),
            }
    return latest


def _implementing_agent(
    repo: str, head_sha: str, branch: str, token: str
) -> str | None:
    """The lease grantee for a PR branch, from the registry at the head.

    Reads ``docs/claims/leases.yaml`` at the head and takes the grantee
    of the most recent grant_history entry for the branch. Returns None
    when the registry is absent, unparsable, or names no grant for the
    branch — the receipt's self-approval check then cannot compare
    agents, which the bundle records by leaving the field empty.
    """
    try:
        import yaml
    except ImportError:
        return None
    try:
        blob = _api_get(
            f"{API_BASE}/repos/{repo}/contents/docs/claims/leases.yaml"
            f"?ref={head_sha}",
            token,
        )
        registry = yaml.safe_load(
            base64.b64decode(blob["content"]).decode("utf-8")
        )
    except (RuntimeError, KeyError, ValueError):
        return None
    if not isinstance(registry, dict):
        return None
    grants = [
        entry
        for entry in registry.get("grant_history", [])
        if isinstance(entry, dict) and entry.get("branch") == branch
    ]
    if not grants:
        return None
    grantee = grants[-1].get("grantee")
    return grantee if isinstance(grantee, str) else None


def fetch_evidence(repo: str, head_sha: str, token: str) -> dict[str, Any]:
    """Build the evidence bundle for `head_sha` from the live API.

    Resolves the head to its pull request (a head with no PR cannot be
    evaluated: there is no author, no base, and no review surface), then
    reads the PR's check runs, reviews, and receipt comments, plus the
    merge-base of main and the head. Raises ValueError when no PR names
    the head, RuntimeError on an API failure.
    """
    pulls = _api_get(
        f"{API_BASE}/repos/{repo}/commits/{head_sha}/pulls", token
    )
    if not pulls:
        raise ValueError(f"no pull request names head {head_sha}")
    pull = pulls[0]
    number = pull["number"]
    author = pull["user"]["login"]
    base_branch = pull["base"]["ref"]

    check_runs = _api_get(
        f"{API_BASE}/repos/{repo}/commits/{head_sha}/check-runs?per_page=100",
        token,
    )
    reviews = _api_get(
        f"{API_BASE}/repos/{repo}/pulls/{number}/reviews?per_page=100", token
    )
    comments = _api_get(
        f"{API_BASE}/repos/{repo}/issues/{number}/comments?per_page=100",
        token,
    )
    compare = _api_get(
        f"{API_BASE}/repos/{repo}/compare/{base_branch}...{head_sha}", token
    )
    main = _api_get(f"{API_BASE}/repos/{repo}/branches/{base_branch}", token)

    # The lease grantee for this PR's branch, from the registry at the head.
    implementing_agent = _implementing_agent(
        repo, head_sha, pull["head"]["ref"], token
    )

    return {
        "head_sha": head_sha,
        "base_sha": (compare.get("merge_base_commit") or {}).get("sha"),
        "main_head_sha": (main.get("commit") or {}).get("sha"),
        "author": author,
        "implementing_agent": implementing_agent,
        "checks": _latest_check_runs(check_runs.get("check_runs", []), head_sha),
        "reviews": [
            {
                "user": (review.get("user") or {}).get("login"),
                "state": review.get("state"),
                "commit_id": review.get("commit_id"),
                "submitted_at": review.get("submitted_at"),
            }
            for review in reviews
        ],
        "receipts": parse_receipts(comments),
    }


def live_state(repo: str, bundle: dict[str, Any], token: str) -> dict[str, Any]:
    """Current base state for evaluating a stored bundle.

    Returns the live merge-base of main and the bundle head, the live
    main head, and whether the bundle head is still an ancestor of the
    live head (a force-push rewrite makes it not one).
    """
    head_sha = bundle["head_sha"]
    pulls = _api_get(
        f"{API_BASE}/repos/{repo}/commits/{head_sha}/pulls", token
    )
    if not pulls:
        raise ValueError(f"no pull request names head {head_sha}")
    pull = pulls[0]
    base_branch = pull["base"]["ref"]
    live_head = pull["head"]["sha"]
    compare = _api_get(
        f"{API_BASE}/repos/{repo}/compare/{base_branch}...{head_sha}", token
    )
    main = _api_get(f"{API_BASE}/repos/{repo}/branches/{base_branch}", token)
    ancestry = _api_get(
        f"{API_BASE}/repos/{repo}/compare/{head_sha}...{live_head}", token
    )
    merge_base = (ancestry.get("merge_base_commit") or {}).get("sha")
    return {
        "base_sha": (compare.get("merge_base_commit") or {}).get("sha"),
        "main_head_sha": (main.get("commit") or {}).get("sha"),
        "head_is_ancestor": merge_base == head_sha,
    }


def main(argv: list[str] | None = None) -> int:
    """CLI: evaluate a head's merge evidence.

    Live mode (default) fetches the evidence bundle for --head from the
    API and evaluates it; --bundle-out writes the fetched bundle for
    audit. Stored-bundle mode (--bundle) evaluates a bundle file instead:
    with --repo it also fetches the live base state, so a stored bundle
    recorded at an older head or base is rejected as invalidated-base.
    Prints the verdict as JSON. Exit 0 on allow, 1 on reject, 2 on
    usage or fetch errors. The token comes from GITHUB_TOKEN (or
    --token); it is never printed.
    """
    parser = argparse.ArgumentParser(
        description="Evaluate whether the merge evidence permits a merge."
    )
    parser.add_argument("--repo", default="")
    parser.add_argument("--head", required=True)
    parser.add_argument("--token", default="")
    parser.add_argument("--bundle", default="")
    parser.add_argument("--bundle-out", default="")
    args = parser.parse_args(argv)

    token = args.token or os.environ.get("GITHUB_TOKEN", "")
    try:
        if args.bundle:
            bundle = json.loads(Path(args.bundle).read_text(encoding="utf-8"))
            live = None
            if args.repo:
                if not token:
                    raise ValueError(
                        "--bundle with --repo needs a token "
                        "(GITHUB_TOKEN or --token)"
                    )
                live = live_state(args.repo, bundle, token)
            result = evaluate(args.head, bundle, live=live)
        else:
            if not args.repo:
                raise ValueError("live mode needs --repo")
            if not token:
                raise ValueError(
                    "live mode needs a token (GITHUB_TOKEN or --token)"
                )
            bundle = fetch_evidence(args.repo, args.head, token)
            if args.bundle_out:
                Path(args.bundle_out).write_text(
                    json.dumps(bundle, indent=2), encoding="utf-8"
                )
            result = evaluate(args.head, bundle)
    except (ValueError, RuntimeError, OSError, KeyError) as error:
        print(json.dumps({"error": str(error)}))
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result["verdict"] == "allow" else 1


if __name__ == "__main__":
    raise SystemExit(main())
