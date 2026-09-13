# Branch constitution

Default branch: `main`.
Observed workflow: PRs into main; both squash-shaped commits and bot branches exist. Preserve actual merge practice case by case.
Worktrees: one per active short-lived working branch. Programme categories are issue metadata, not automatic new branches.

## Standing branches

| Branch | Purpose | May receive | Green means | Must never contain |
| --- | --- | --- | --- | --- |
| main | Releasable reusable learning runtime and honest documentation | Reviewed, bounded PRs whose evidence matches head and relevant base | Supported Python matrix, lint/types, CLI/docs gates, tests, required security/data contracts, and purpose invariants; check identity verified | Secrets, populated personal profiles/databases, unsupported success claims, unrelated unfinished work |

No develop, master or lane/* branch is established from the current evidence. Recurring work alone does not prove a lane helps: an issue must justify integration need, synchronization method, review ownership and CI coverage before one is adopted. A lane adopted later remains standing or explicitly dormant until a reviewed retirement decision.

## Existing working and preservation refs

| Ref | Treatment | Merge target |
| --- | --- | --- |
| learning/plan-integrity-v2-2026-09-08 | Existing PR20 owner; retain its name while healing | main |
| dependabot/github_actions/github-actions-deps-6af9ef796d | Existing PR19/family owner; preserve unique sibling choices | main |
| capture/main-heal-2026-07-02T13-14-42Z | Parked preservation source; recover every unique hunk before any retirement | Extract justified residue through a bounded PR to main; no wholesale merge |
| wip/preserve-2026-05-31-adaptive-personal-syllabus | Parked preservation source; same custody rule | Extract justified residue through the same recovery intention |

## New work

Use `feat|fix|chore|docs|test/<short-intent>` or `work/<program>/<short-intent>` from the verified target base. A work/* program segment names queue ownership and does not imply a standing lane exists.
Every grant records repository ID, issue, base SHA, existing or proposed branch, write scope and merge target. An agent reads adopted BRANCHES.md before creating any branch.
One intention per PR; one successor per repeated-root-cause family. Preserve source commits/comments and unique residue. No direct work commits on main, even while the API reports it unprotected.
Hotfix/* starts at main for a proven production break, returns by PR, and is back-ported only to actual living lanes that need it.
Release/* is introduced only by an evidenced freeze requirement for a versioned artifact; otherwise tags/releases come from verified main.

## Integration and retirement

An independent review and all applicable tests bind exact head plus relevant base/policy/source versions. New head invalidates old head-specific evidence. Integrate serially and verify default afterwards.
Delete a short-lived working branch only after successful integration, verified finish line, and a preservation/closure receipt. Preservation refs require a separate explicit retirement decision.
Preservation refs and any future standing lanes require explicit retirement with no lost unique work. Dormancy is a state, not permission to delete.
Unpublished work must be captured with a patch/bundle or durable remote branch in its proper privacy boundary before handoff.

