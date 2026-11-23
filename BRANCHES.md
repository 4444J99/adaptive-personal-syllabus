# Branch constitution

Default branch: `main`.
Observed workflow: PRs into main; both squash-shaped commits and bot branches exist. Preserve actual merge practice case by case.
Worktrees: one per active short-lived working branch. Programme categories are issue metadata, not automatic new branches.

## Standing branches

| Branch | Purpose | May receive | Green means | Must never contain |
| --- | --- | --- | --- | --- |
| main | Releasable reusable learning runtime and honest documentation | Reviewed, bounded PRs whose evidence matches head and relevant base | Supported Python matrix, lint/types, CLI/docs gates, tests, required security/data contracts, and purpose invariants; check identity verified | Secrets, populated personal profiles/databases, unsupported success claims, unrelated unfinished work |

No develop, master or lane/* branch is established from the current evidence. Recurring work alone does not prove a lane helps: an issue must justify integration need, synchronization method, review ownership and CI coverage before one is adopted. A lane adopted later remains standing or explicitly dormant until a reviewed retirement decision.

## Issue ownership

Every open issue resolves to an owning branch, a base SHA, and a merge target below — or to an explicit "no branch yet — unclaimed" row, so unowned work is visible, not silently dropped. Merged rows name the PR and merge commit that integrated the branch; per the retirement rule below, a merged short-lived branch is deletion-earned (deletion itself is a separate step, never performed by a docs PR). Base SHAs are the verified main head at claim time, refreshed at PR time if main moved.

Verified at main `524f57ab` (2026-11-22): every remote branch is accounted for in this table. Corrections to the previous table, verified live this run: the dependabot row cited hash `6af9ef796d`, which matches no live branch — both live Dependabot branches have since merged (PR #77, PR #78) and are listed with their dispositions; the `learning/`, `branch-constitution`, and `ingest-boundary` rows said "retain" but all three branches merged (PR #20, #70, #71) and are deletion-earned; the branches the previous table did not list at all — `work/mentor/audit-truth-contract`, `fix/ledger-…`, `chore/pin-runner-…`, `chore/remove-third-party-transcript`, `work/mentor/ci-baseline`, `work/mentor/control-reconciliation`, `ranked-queue/aps32-toolchain-residue`, `work/mentor/privacy-classification`, `work/mentor/ingest-canary-boundary`, `work/mentor/public-private-contract` — all had merged PRs and are listed with their dispositions. No branch is currently unowned: the five refs the previous drive called orphans all turn out to have merged PRs (#74, #75, #76, #77, #78).

| Issue | Owning branch | Base SHA | Merge target | Status |
| --- | --- | --- | --- | --- |
| #6 (ACTIVATION AUDIT: ship-soon) | no branch yet — unclaimed | — | main | Unclaimed; release-gated |
| #21 (MTR-000, control plan) | work/mentor/control-reconciliation | `3ba8f32` | main | Merged via PR #79; head on main. Future #21 work uses fresh short-lived branches |
| #22–#30 (epics E01–E09) | no branch yet — unclaimed | — | main | Unclaimed |
| #31 (MTR-001, closed) | work/mentor/ci-baseline | `2795435` | main | Merged via PR #80; head on main |
| #32 (MTR-002, closed) | ranked-queue/aps32-toolchain-residue | `27b92f41` | main | Merged via PR #81 (`f8325de8`); head on main |
| #33 (MTR-006) | work/mentor/privacy-classification | `7a517249` | main | Merged via PR #82 (`0060a8e1`); head on main. Shared dependency `work/mentor/ingest-boundary` merged via PR #71 (`6d39e28`, Refs #33/#34) |
| #34 (MTR-007) | work/mentor/ingest-canary-boundary | `2d03c208` | main | Merged via PR #83 (`363c7b1c`); head on main. Shared dependency `work/mentor/ingest-boundary` merged via PR #71 (`6d39e28`, Refs #33/#34) |
| #35 (MTR-009) | work/mentor/issue-ownership | `524f57ab` | main | In progress (this PR). First adoption: `work/mentor/branch-constitution` via PR #70 (`7010ef1`), merged |
| #36 (MTR-010) | work/mentor/agent-claims | `8dc861bc` | main | In progress (this PR); gated on #35 landing, satisfied by PR #85 (`8dc861bc`) |
| #37 (MTR-011) | work/mentor/merge-evidence | `38d87112` | main | In progress (this PR); gates on #35/#36 satisfied by PR #85 (`8dc861bc`) and PR #86 (`38d87112`) |
| #38 (MTR-039) | work/mentor/audit-evidence-status | `6b2b4b90` | main | In progress (this PR); supersedes work/mentor/audit-truth-contract (PR #72's merged branch, `0235b95c`, still exists — reuse would carry #72's history); #31 gate satisfied (PR #80); #37 merged (PR #87) |
| #39 (closed) | learning/plan-integrity-v2-2026-09-08 | `888402e` | main | Merged via PR #20 (`019dfc7`); branch diff identical to the squash (20 files, 2323+/555-) |
| #40 (MTR-004) | work/mentor/capture-residue | `6b2b4b90` | main | In progress (this PR). Preservation refs `capture/main-heal-2026-07-02T13-14-42Z` (`b6f2f9f`, 1 ahead / 42 behind) and `wip/preserve-2026-05-31-adaptive-personal-syllabus` (`c48a55a`, 1 ahead / 47 behind) stay parked — no wholesale merge, no deletion. Disposition at this head: the 19 `.pyc` paths are gone from main (removed by PR #80, #31) so that residue is moot; the README carry-forward (legacy `generate` usage, `aps-data-export`, default data dir) lands in this PR; the CLAUDE.md / GEMINI.md trim is NOT enacted — all 40 removed SOP rows are still live on main with no retiring evidence, so both files are unchanged |
| #41 (MTR-005) | no branch yet — unclaimed | — | main | Unclaimed |
| #42 (MTR-008) | work/mentor/public-private-contract | `fc5a41ef` | main | Merged via PR #84 (`524f57ab`); head on main |
| #43 (MTR-012) | work/mentor/repository-layout (proposed, not yet created) | `019dfc70` (plan base; refresh at build time) | main | Planned; branch named in the #43 plan, not yet created |
| #44 (MTR-013) | no branch yet — unclaimed | — | main | Unclaimed; #45/#46/#47 chain-gated on #44's decision |
| #45, #46, #47 (MTR-014/015/016) | no branch yet — unclaimed | — | main | Unclaimed; chain-gated on #44 |
| #48 (MTR-017) | work/mentor/source-admission | `8ee1538f` | main | In progress (this PR); source admission record |
| #49–#69 (MTR-019–MTR-038, except #50/#52/#54/#68) | no branch yet — unclaimed | — | main | Unclaimed (planned) |
| #50 (MTR-020), #68 (MTR-037) | no branch yet — unclaimed | — | main | Unclaimed (planned; plans name no branch) |
| #52 (MTR-022) | work/mentor/ledger-consistency | `96459abc` | main | Merged via PR #91 (`8f9685c5`); ledger checkpoint + atomic plan-generate; corpus ingest already atomic at this head (verified, no change); docs.audit / artifact appends named-why, not re-transactioned |
| #54 (MTR-018) | work/mentor/live-source-loop | `8f9685c5` (base refreshed at PR time: PR #91 merged first) | main | In progress (this PR); live-source refresh loop |
| — (no owning issue recorded) | fix/ledger-malformed-payload-integrity-failure-14391782578113217034 | `dc0341d` | main | Merged via PR #74 (`cc39b56`); branch content verified identical on main (2/2 files) |
| — (no owning issue recorded) | chore/pin-runner-ubuntu-2404-20261012 | `a7c20a1` | main | Merged via PR #75 (`5659bee4`, runner pin, Anthony-approved Oct 12); the follow-up ruff `--fix` hunks are superseded by later main work |
| — (no owning issue recorded) | chore/remove-third-party-transcript | `75f700e` | main | Merged via PR #76 (`3ba1c28`); the committed runtime `.db` blob exists only on the branch and must not be merged |
| — (no owning issue recorded) | dependabot/github_actions/github-actions-deps-696b649f44 | `df1cf5c` | main | Merged via PR #78 (`6530a2d`, setup-python 6→7); branch head patch-equivalent on main |
| — (no owning issue recorded) | dependabot/github_actions/github-actions-deps-84c3d95bcf | `8ade22d` | main | Merged via PR #77 (`7c0821c`, stale 10→11); branch head patch-equivalent on main |

The privacy-classification inventory (`docs/privacy-classification.yaml`,
decisions in `docs/adr/003-privacy-classification.md`) classifies the two
preservation refs above as `review`: each unique hunk is classified before
any extraction; nothing is extracted unclassified.

## New work

Use `feat|fix|chore|docs|test/<short-intent>` or `work/<program>/<short-intent>` from the verified target base. A work/* program segment names queue ownership and does not imply a standing lane exists.
Every grant records repository ID, issue, base SHA, existing or proposed branch, write scope and merge target. An agent reads adopted BRANCHES.md before creating any branch.
One intention per PR; one successor per repeated-root-cause family. Preserve source commits/comments and unique residue. No direct work commits on main, even while the API reports it unprotected.
Hotfix/* starts at main for a proven production break, returns by PR, and is back-ported only to actual living lanes that need it.
Release/* is introduced only by an evidenced freeze requirement for a versioned artifact; otherwise tags/releases come from verified main.

## Integration and retirement

An independent review and all applicable tests bind exact head plus relevant base/policy/source versions. New head invalidates old head-specific evidence. Integrate serially and verify default afterwards.
The contract that decides what evidence permits a merge is docs/merge-evidence.md (ADR 007).
Delete a short-lived working branch only after successful integration, verified finish line, and a preservation/closure receipt. Preservation refs require a separate explicit retirement decision.
Preservation refs and any future standing lanes require explicit retirement with no lost unique work. Dormancy is a state, not permission to delete.
Unpublished work must be captured with a patch/bundle or durable remote branch in its proper privacy boundary before handoff.
