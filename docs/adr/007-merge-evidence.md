# ADR 007 — Merge evidence: the contract that permits a merge

- Status: accepted (bounded decision for #37, MTR-011)
- Decided: 2026-11-22, in PR `work/mentor/merge-evidence` (ranked-queue loop)
- Context: #37, implementation plan posted 2026-11-18 (comment 6969699762),
  re-verified live at main `38d87112` before building. Parent epic #24,
  control plan #21. Depends on #35 (merged via PR #85) and #36 (merged
  via PR #86) — both landed before this build, so the Step 3 decision
  consumes their real outcomes: #35's ownership table (BRANCHES.md) and
  #36's lease registry (`docs/claims/leases.yaml`).
- Evidence base: live tree at `38d87112` (post-#86 merge, 10/10 checks
  green, 0 open PRs), verified through the GitHub API. Fact recovery at
  that head: main reports `protected: false`, the protection endpoint
  returns 404 "Branch not protected", and `GET /rulesets` returns `[]`;
  the merge policy exists only as prose in BRANCHES.md; CI is green at
  the head — the gap is enforcement, not signal; no merge-evidence code
  exists anywhere in the 191-path tree (no path names merge-evidence,
  protection, or ruleset); the six workflows are ci, codeql,
  privacy-classification, release-drafter, secret-scan, stale; the live
  check runs at the head are `test (3.11)`, `test (3.12)`,
  `Analyze Code (python)`, `Secret Pattern Detection`, `classification`,
  `clean-checkout`, `build`, `deploy`, `report-build-status`,
  `update_release_draft`, plus the advisory bots CodeRabbit, Sourcery
  review, and `semgrep-cloud-platform/scan`. The three missing predicates
  from the plan's step 1 reproduce by inspection at this head: (a) a
  merge may ignore every green check and still land, because nothing
  requires any check; (b) an approval recorded at an older head is never
  compared to the current head, because nothing records approvals at
  all; (c) author == approver is never checked, because no review of
  any kind is required. The counterexample is the estate's own recent
  practice: PR #86 was opened by the 06:15 executor run and merged by
  the 06:44 batch run at 10/10 checks green with zero reviews on the
  PR — the verification was real (a separate run did it) but left no
  review artifact on the PR in any form the repo can check, so the merge
  was permitted by nothing but the merger's judgment at merge time. The
  receipt fixes the recording, not the independence. The six rejection
  reasons are exercised as synthetic bundles in
  `tests/test_merge_evidence.py`; the contract document names every
  required check and every reason, and a test asserts it cannot drift
  from the code.

## Decision

1. **Q1 — which authenticated check producers are trusted?** Exactly
   six, named in `docs/merge-evidence.md`: `test (3.11)`, `test (3.12)`
   (code correctness on the supported matrix, including ruff, mypy, CLI
   smoke, and the docs audit gate), `Analyze Code (python)` (the CodeQL
   producer), `Secret Pattern Detection` (the secret-scan producer),
   `classification` (the #33 security/data contract), and
   `clean-checkout` (the #42 public-surface proof). The last two
   postdate the plan — the plan's set was the first four — and they are
   required because BRANCHES.md's standing table already names
   "required security/data contracts" as what green means on main, and
   both are repo-adopted contracts a merge must not silently break.
   Advisory, never required: the pages build and deploy, the release
   drafter, and the review bots (CodeRabbit, Sourcery,
   `semgrep-cloud-platform/scan`) — a merge is never permitted on
   advisory evidence alone, and an advisory failure never blocks a merge
   on its own. No producer is trusted by default; each must be named.
2. **Q2 — which review roles are trusted?** The owner (Anthony), and
   one designated agent reviewer: the `pr-merge-batches` job, whose
   review is recorded as a receipt comment on the PR, not as a GitHub
   review — all loop work authenticates as one login, so a GitHub
   approval from the loop cannot be distinguished from the author's.
   The receipt names the reviewing job and the head it binds; the
   evaluator re-fetches the checks itself and never trusts a receipt's
   claims about checks. Owner-only approval was rejected as the
   default: it would strand every loop PR on Anthony's per-PR review
   and contradict the standing authorization under which merges flow
   through the batch. The batch's receipt IS the independent review
   because the batch is a separate run from the executor that opened
   the PR — different job, different run, no shared state but the repo.
   Self-approval stays rejected: a GitHub approval by the author, or a
   receipt from the implementing agent (the lease grantee for the PR
   branch), is rejected even when the agent is a designated reviewer
   job — the batch opening a PR and then receipting it would approve
   itself. A second human is never required by this contract.
3. **Q3 — which head/base/policy changes invalidate earlier evidence?**
   Any new head (every required check and every approval must bind the
   exact merge head); a stored evidence bundle whose base moved (main
   advanced past the recorded merge-base) or whose head was rewritten
   (no longer an ancestor of the live head, e.g. by a force-push);
   any change to `.github/workflows/` or to the required-check list
   itself. Base freshness is NOT a merge gate: a PR need not rebase on
   every main move — `invalidated-base` guards a recorded evidence
   bundle, not a PR's freshness. Serial integration, rollback,
   family-member closure, and partial failures are recorded as one
   closure receipt per integrated head, per BRANCHES.md; a merge that
   lands with a failing required check is a contract violation,
   recorded as one, not a passing merge; rollback is a new PR, never a
   history rewrite.
4. **Q4 — enforcement vehicle.** A repository ruleset on `main` (the
   current mechanism; legacy branch protection is not used), naming
   exactly seven required checks — the six above plus the
   `merge-evidence` workflow check itself — with force-pushes and
   branch deletion blocked, and no GitHub-review-count requirement:
   the review is enforced inside the merge-evidence check, where a
   receipt can count, and a ruleset review count could only count
   GitHub reviews. The settings change is Anthony's action; this PR
   builds the contract, the tests, the workflow, and this record, and
   the workflow stays advisory until the ruleset is enabled and
   re-read from the API.
5. **Dependency revision (required by #37).** #35 and #36 are both
   merged; the order stands, no cycle, no lost intention. #37 consumes
   #35's ownership table (the #37 row moves from unclaimed to this
   branch) and #36's lease registry (the implementing-agent comparison
   reads the grant for this branch, recorded here as sequence 2).

## What is automated, what stays human

- Automated evaluation (`src/adaptive_personal_syllabus/merge_evidence.py`):
  the pure `evaluate` (six rejection reasons, one per failing
  predicate), the API fetcher that builds the bundle from the Checks
  and Reviews APIs at the head, the receipt parser, and the CLI
  (`python -m adaptive_personal_syllabus.merge_evidence`) that prints
  the verdict as JSON and exits non-zero on reject. The workflow
  (`.github/workflows/merge-evidence.yml`) runs the CLI on every PR
  head and fails the PR's `merge-evidence` check on reject. The module
  never changes a setting; it only evaluates what is recorded.
- Human/steward procedure: enabling the ruleset on main (ADR step 4),
  granting leases, and flipping a lease to fulfilled/expired after its
  work lands. The batch's merge procedure after this lands: verify the
  evidence at the head, post a receipt comment naming the head, re-run
  the workflow, and merge only when the check is green.

## What this deliberately does NOT do

- No change to any branch protection, ruleset, or repository setting:
  the settings half is named, sequenced, and left to Anthony.
- No re-decision of #35 (who owns issues/branches) or #36 (exclusive
  claims/handoffs): #37 consumes their outcomes; if they had been
  undecided when this decision ran, it would have recorded "owner-only
  approval" as the interim and named #35/#36 as the follow-up.
- No weakening of any existing check to make the contract pass; no
  editing of tests to mirror code; no `merge/` directory — the module
  lives in `src/adaptive_personal_syllabus/merge_evidence.py`, the
  plan's own first alternative, following the #36 `agent_claims.py`
  precedent (the issue's declared `merge/` scope predates it).
- No technical fencing for work that never obtained a lease, and no
  claim that the receipt path is cryptographically strong: it relies on
  run separation plus auditability (see Remaining uncertainty), which
  is the same trust the whole estate already runs on, recorded here
  rather than hidden.
- No private learner data in merge evidence, ever.

## Alternatives considered and rejected

- **Owner-only approval.** Rejected as the default: it would strand
  every loop PR on a per-PR review and contradict the standing
  authorization under which merges flow through the batch. The owner
  remains a trusted approver; he is not the only one.
- **Checks-only gate (no approval required).** Rejected: the issue
  explicitly asks which review roles are trusted, and a checks-only
  gate would let an executor merge its own PR the moment CI is green
  — the self-approval failure mode the issue names.
- **GitHub reviews as the only approval.** Rejected: all loop work
  authenticates as one login, so a GitHub approval from the loop is
  indistinguishable from the author's; the receipt carries the review
  identity the Checks API cannot.
- **Legacy branch protection instead of a ruleset.** Rejected: the
  ruleset is the current mechanism, and it expresses the required-check
  list (including the merge-evidence check itself) directly.
- **Polling inside the workflow until checks complete.** Rejected: it
  would burn a runner per PR for the whole CI duration on an estate
  already over its Actions budget. The workflow evaluates once per
  trigger; re-evaluation after CI completes is a re-run, automated by
  the `check_run` trigger once this lands on main.

## Remaining uncertainty

- The receipt path relies on run separation plus auditability, not on
  cryptographic identity: anyone with write access could post a
  receipt naming `pr-merge-batches`. A forged receipt would be visible
  in the PR timeline and would name a run whose records do not show the
  verification — the steward corroborates receipts against run
  records. If that boundary ever proves insufficient, the fix is a
  stronger reviewer identity, not a weaker contract.
- The `check_run` trigger only takes effect after this workflow lands
  on main; on the PR that introduces it, re-evaluation after CI
  completes is a manual re-run. A PR whose checks complete after the
  last trigger shows a stale verdict until re-run — the batch's
  procedure (verify, receipt, re-run) covers it, but it is a manual
  step until the trigger is live.
- A ruleset requiring the `merge-evidence` check fails closed: if the
  workflow itself breaks, no PR can merge until it is fixed. That is
  the intended behavior (a broken gate blocks rather than passing),
  but it makes the workflow a single point of failure for merges.
- The evaluator reads the latest review per user; a review dismissed
  after approval correctly stops counting, but a reviewer who approves,
  then comments without re-approving after a new head, leaves the old
  approval stale — which is the contract working as designed, not a
  gap, and is recorded here so the behavior is not mistaken for one.

## Appendix — deviation from the plan

- The plan named the decision record `docs/adr/004-merge-evidence.md`.
  004 is the #34 ingest ADR, 005 the #42 contract ADR, and 006 the #36
  claims ADR, so this record is 007. The number is the only change in
  the decision record's identity; the content follows the plan's step 3.
- The plan's required set was test 3.11, test 3.12, ruff via CI,
  CodeQL, Secret Scan. The live set at `38d87112` is the six checks
  named in Q1: `classification` and `clean-checkout` are added (both
  postdate the plan and are repo-adopted contracts), and the check-run
  names are used (`Analyze Code (python)` for the CodeQL producer,
  `Secret Pattern Detection` for secret scan; ruff runs inside the
  test job, not as its own check).
- The plan verified at main `019dfc70`; this build re-verified every
  load-bearing claim at `38d87112` (post-#85/#86). Main is still
  unprotected with no rulesets; the plan's step-1 claim (no mechanism
  exists) is unchanged by the head move.
