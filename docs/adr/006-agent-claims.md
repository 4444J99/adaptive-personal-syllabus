# ADR 006 — Agent claims: the steward grants the lease, the check enforces it

- Status: accepted (bounded decision for #36, MTR-010)
- Decided: 2026-11-22, in PR `work/mentor/agent-claims` (ranked-queue loop)
- Context: #36, implementation plan posted 2026-11-18 (comment 6971129810),
  re-verified live at main `8dc861bc` before building. Parent epic #24,
  control plan #21. Depends on #33 (merged via PR #82) and #35 (merged via
  PR #85) — both landed before this build, so steps 3–5 of the plan proceed.
- Evidence base: live tree at `8dc861bc` (post-#85 merge, 10/10 checks
  green, 0 open PRs), verified through the GitHub API. Fact recovery at
  that head: no lease, claim, or handoff mechanism exists anywhere in
  `src/`, `tests/`, or `docs/` (tree search: no path names lease, claim,
  or handoff outside release-drafter config); AGENTS.md stewardship rules
  say claims in comments are procedural and provide no technical locks;
  `docs/adr/` holds 001–005 only; the one handoff rule lives in prose
  (BRANCHES.md, "Unpublished work must be captured … before handoff") and
  nothing checks it; `work/mentor/agent-claims` does not exist among the 19
  remote refs; `work/mentor/audit-truth-contract` is still live at
  `0235b95c`, 1 ahead / 27 behind main. The three missing predicates from
  the plan's step 1 reproduce by inspection at this head: (a) two agents
  claiming overlapping scope both succeed today, because nothing checks;
  (b) a claim "expires" and nothing enforces it — an expired claim is
  indistinguishable from a live one; (c) a claim recorded at a stale base
  is never compared to current main. The four acceptance cases are
  exercised as synthetic tasks in `tests/test_agent_claims.py`, with the
  receipt asserted in each case, not just the verdict. The test suite was
  not executed locally in this run, so CI at the PR head is the acceptance
  gate for the code below.

## Decision

1. **Q1 — who grants the single authoritative claim?** The steward
   grants it; the grant is a record in `docs/claims/leases.yaml`, not a
   comment. One active lease per scope, identified by grant sequence.
   A lease records grantee, issue, grant sequence, base/head, branch,
   scope (repo-relative paths; a trailing `/` covers a directory), expiry,
   receipt, and status (`active` | `fulfilled` | `expired` | `revoked`).
   Overlapping scope is a conflict and is refused with a receipt citing
   the holding lease's sequence and grantee. Scope values come from #35's
   issue-ownership table; classification constraints come from #33's
   inventory — a scope path that does not classify `public` is refused.
2. **Q2 — expiry, revocation, overlapping write scopes.** Expiry is a
   field on the lease, enforced by the check, not by memory: an expired
   lease frees its scope and the expiry is itself recorded in the
   receipt (`frees-expired-lease=N`). An `active` lease past expiry is a
   registry violation — the self-check fails until the steward flips it
   to `expired`. Revocation is a steward action recorded the same way.
   Shared contracts count as overlap; the lease narrows the scope instead
   of the check widening it. A claim from the grantee who already holds
   the overlapping lease is allowed as an extension of that lease.
3. **Q3 — the minimal handoff.** Issue + lease owner + base/head + write
   scope + expiry + receipt + the unpublished-work capture required by
   BRANCHES.md (patch/bundle or durable remote branch). The schema is
   `docs/claims/handoff.md`; a handoff missing any item is refused.

## What is automated, what stays human

- Automated fencing (`src/adaptive_personal_syllabus/agent_claims.py`):
  grant-time evaluation (`evaluate_claim`), registry consistency
  (`self_check`, run in CI), and the PR gate (`pr_check`, run in CI on
  the PR's changed files against active leases held by other grantees,
  plus the PR's own lease expiry and base staleness). The module never
  grants, revokes, or writes the registry; it only evaluates what is
  recorded in it.
- Human/steward procedure: granting a lease, revoking one, settling an
  ownership dispute, and flipping a lease to `fulfilled`/`expired` after
  its work lands or its expiry passes. Grant-time evaluation is
  steward-operated through the module's `--evaluate-claim` mode; the
  receipt it prints goes into the grant record.

## What this deliberately does NOT do

- No claim of technical fencing for work that never obtained a lease:
  the registry fences recorded scopes. A PR with no lease of its own
  fails only when its changed files fall inside another grantee's active
  lease; a PR touching unleased files passes the gate. The fence is only
  as complete as the leases recorded in it — which is why the grant, not
  the check, is the authoritative act.
- No lease is granted over an unowned branch. `work/mentor/audit-truth-
  contract` is recorded in the registry as unowned (content on main via
  PR #72; ownership sits with #38/#40); a claim naming it is refused
  until the ownership table gives it a live owner. The two preservation
  refs are recorded the same way.
- No branch deletions; no change to #21's queue; no private evidence in
  public issue text. No history rewrite, no settings change.

## Alternatives considered and rejected

- **Comment-only claims (status quo).** Rejected: the issue's own premise
  is that comments are not atomic locks, and the step-1 reproductions
  show all three predicates failing. Keeping it would be re-asserting the
  gap as the mechanism.
- **GitHub-native locks (branch protection / CODEOWNERS).** Rejected as
  the mechanism: neither expresses an expiry, a per-agent scope, or an
  overlap decision, and neither can refuse a claim with a receipt citing
  the holding lease. Kept as complementary where they already exist.
- **A central claim service or database.** Rejected: it would need
  infrastructure, credentials, and a second source of truth outside the
  repo. The lease file is versioned with the code it fences, reviewable
  in the same PR, and readable without any service.

## Remaining uncertainty

- The CI pr-check fences changed files against recorded leases; it
  cannot detect two agents who both work unleased scopes and collide on
  merge. That collision is still caught by review and by the merge
  itself, not by this check — recorded here so the boundary is visible.
- Lease expiry is wall-clock UTC; a lease granted with an expiry far in
  the future is effectively unexpiring until the steward revokes it. The
  first grant's expiry is one week from grant; the steward sets later
  expiries per claim.
- The registry's active list is empty at this head: the first grant
  (#36, this PR) is the work that creates the registry, so it is
  recorded in `grant_history` with its receipt, and the steward flips it
  to `fulfilled` when the PR merges. A future grant goes in `leases`
  while in flight.

## Appendix — deviation from the plan

- The plan named the decision record `docs/adr/003-agent-claims.md`.
  003 is the #33 privacy-classification ADR, 004 the #34 ingest ADR, and
  005 the #42 public/private contract ADR, so this record is 006. The
  number is the only change; the content follows the plan's step 2.
- The plan's step-1 baseline counted 12 remote branches; the live count
  at `8dc861bc` is 19 refs. The claim in step 1 (no mechanism exists) is
  unchanged by the count.
