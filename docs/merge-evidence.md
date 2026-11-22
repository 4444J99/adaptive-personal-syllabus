# Merge evidence — what permits a merge

**Status of this plan:** This is one take, not a solidified plan. It is my current version of what I think should work, based on the source verified at the head named in the plan, and it needs further investigation and further hardening before and during implementation. Each step includes my reasoning for why, so the plan can be checked rather than trusted; where live evidence disagrees with the plan, the evidence wins and the plan gets revised.

Main reports `protected: false` and `rulesets: []` (verified 2026-11-22 at
`38d87112`). Nothing in the GitHub settings layer requires a check, a
review, or anything else before a merge — and nothing forbids a direct
push, a force-push, or branch deletion. The merge policy in BRANCHES.md
("Reviewed, bounded PRs whose evidence matches head", "New head
invalidates old head-specific evidence") is a constitution with no
enforcement behind it. This document is the contract as code: it states
exactly what evidence permits a merge, and the module
`src/adaptive_personal_syllabus/merge_evidence.py` evaluates it. The
decision behind the contract is ADR 007.

## The trusted check set (required)

A merge requires every one of these checks, run at the exact merge head
with conclusion `success`. No producer is trusted by default; each is
named here because it proves something the merge depends on:

| Check | What it proves | Why it is required |
| --- | --- | --- |
| `test (3.11)` | The test suite passes on Python 3.11 (incl. ruff, mypy, CLI smoke, docs audit gate) | Code correctness on the supported matrix |
| `test (3.12)` | The test suite passes on Python 3.12 | Code correctness on the supported matrix |
| `Analyze Code (python)` | CodeQL analysis of the Python code | The CodeQL producer the repo runs (workflow `codeql.yml`) |
| `Secret Pattern Detection` | No secret pattern in the diff | The secret-scan producer the repo runs |
| `classification` | Every tracked path classifies under the #33 inventory, exactly once | The repo's security/data contract (#33) |
| `clean-checkout` | A clean public checkout builds, passes, and runs the end-to-end flow with no sibling seed and no credentials | The #42 public-surface proof |

Advisory, not required: `build`, `deploy`, `report-build-status`,
`update_release_draft` (pages build, release drafting — informational,
they do not gate code correctness), `CodeQL` (the workflow-level run
for the same producer as `Analyze Code (python)`), `CodeRabbit`,
`Sourcery review`, `semgrep-cloud-platform/scan` (third-party review
bots whose trust is not established in this repo). A merge is never
permitted on advisory evidence alone, and an advisory failure never
blocks a merge on its own — but it is still read before merging.

## The head-binding rule

Evidence binds the exact head SHA it was recorded at, and nothing else.
A new head invalidates old head-specific evidence: every required check
must have its latest completed run at the merge head, and every approval
must name the merge head. The evaluator compares run head SHAs from the
Checks API against the merge head; a run at any other head is rejected
as `stale-head`, however green it was.

## Rejection reasons

The evaluator returns `allow` or `reject` with one reason per failing
predicate, from exactly these six:

- `stale-head` — evidence recorded at another head (a check run at an
  older head, an approval recorded at an older head, a receipt binding
  an older head, or no approval binding this head at all).
- `missing-check` — a required check with no recorded run, or whose
  latest run has not completed. A run still in progress has produced no
  completed evidence yet, so it is a rejection, not a pass.
- `skipped-check` — a required check whose conclusion is `skipped`.
  Skipped is not success.
- `failed-check` — a required check whose conclusion is anything other
  than `success` (failure, cancelled, timed out, action required).
- `self-approval` — the author approved the head, or a receipt came from
  the implementing agent. Author == approver is rejected.
- `invalidated-base` — a stored evidence bundle whose base moved (main
  advanced past the recorded merge-base since the evidence was recorded)
  or whose head is no longer an ancestor of the live head (the branch
  history was rewritten, e.g. by a force-push). This reason only fires
  when evaluating a stored bundle against live state; a live evaluation
  builds its bundle from current state.

## Review roles

- **Owner.** Anthony may approve any PR. His approval at the head
  passes the approval predicate.
- **Designated agent reviewer.** The `pr-merge-batches` job is the one
  designated agent reviewer. It verifies the evidence at the head and
  records its review as a receipt (below), not as a GitHub review — all
  loop work authenticates as one login, so a GitHub approval from the
  loop cannot be distinguished from the author's. The receipt is the
  review identity the Checks API cannot carry.
- **No one else.** A GitHub approval by any login other than the author's
  passes; an approval by the author is `self-approval`; a receipt from
  any agent outside the designated list is not an approval.

The implementing agent is the lease grantee for the PR branch (from
`docs/claims/leases.yaml` at the head). A receipt from the implementing
agent is `self-approval`, even when the agent is a designated reviewer
job — the batch opening a PR and then receipting it would approve
itself. The receipt path relies on run separation plus auditability,
not on cryptographic identity: a receipt names its job and head, the
job's run records corroborate it, and a forged receipt would be visible
in the PR timeline. That boundary is recorded in ADR 007, not hidden.

## Review receipts

A receipt is a comment on the PR with this marker line, followed by a
fenced JSON block:

```text
<!-- merge-evidence-receipt -->
```json
{"agent": "pr-merge-batches", "job": "pr-merge-batches", "head": "<head SHA>", "verdict": "allow"}
```
```

`agent` must be a designated reviewer, `head` must be the merge head,
`verdict` must be `allow`. A comment without the marker, or with a block
that does not parse as JSON, contributes nothing — a malformed receipt
is ignored, never trusted. The evaluator re-fetches the checks itself
from the Checks API; it never trusts a receipt's claims about checks.
The receipt supplies only the review identity and the head it binds.

## The workflow, and what it can and cannot do

`.github/workflows/merge-evidence.yml` runs the CLI
(`python -m adaptive_personal_syllabus.merge_evidence`) on every PR head
and fails the PR's `merge-evidence` check when the verdict is `reject`.
It runs on `pull_request` (opened, synchronize, reopened),
`pull_request_review` (submitted), and `check_run` (completed, limited
to the six required checks). Two limits, both honest:

1. The `check_run` trigger only takes effect after this workflow lands
   on main (check-run events run the workflow as defined on the default
   branch). On the PR that introduces the workflow, re-evaluation after
   CI completes happens by re-running the workflow, not automatically.
2. Until the settings half lands (ADR 007, step 4b — Anthony's action),
   the workflow is advisory: it reports the verdict, but the settings
   layer cannot enforce it, and a merge may still ignore it. The
   workflow must never be described as enforcement until the ruleset or
   protection is enabled and re-read from the API.

## Re-evaluating, and the trial

A head that changes after an approval shows the old evidence rejected:
re-running the workflow on the new head evaluates the new head, and the
old approval (or receipt) binds the old head, so the verdict is
`stale-head` until a fresh approval or receipt names the new head.
That is the trial this PR demonstrates: the `merge-evidence` check on
this PR is red while the evidence is incomplete, and turns green only
when green checks at the head plus an independent review at the head
both exist.

After this lands, the merge procedure for a loop PR is: the batch
verifies the evidence at the head, posts a receipt comment naming the
head, and re-runs the workflow; the check turns green, and the batch
merges. A PR with no receipt and no non-author approval stays red on
`merge-evidence` and is not merged under the honest-green rule.

## Invalidation and closure

- A changed head, a changed merge-base, a changed required-check list,
  or a change to `.github/workflows/` invalidates affected evidence.
  The evaluator re-reads the checks live on every run; nothing is
  cached across heads.
- Base freshness is not a merge gate in this contract: a PR need not
  rebase on every main move. The `invalidated-base` reason guards a
  recorded evidence bundle, not a PR's freshness.
- Serial integration, rollback, family-member closure, and partial
  failures are recorded as one closure receipt per integrated head, per
  BRANCHES.md. A merge that lands with a failing required check is a
  contract violation, recorded as one, not a passing merge.
