# Mentor roadmap state — reconciliation receipt

Control plan: #21 ([MTR-000]). This file reconciles the Sep 13, 2026 baseline
against current main, so later waves do not re-derive the same baseline from
scratch. It records what landed, what is half-done, and what is still open —
with the evidence for each verdict, not just the verdict.

- **Recorded at:** main `019dfc70` ("Make learning plans truthful, adaptive,
  and output-optional (#20)", merged 2026-11-14T16:00:03Z)
- **Lease:** ranked-queue loop, branch `work/mentor/control-reconciliation`,
  grant recorded on #21 (comment 7033217509). Repository ID `1156696093`,
  base `019dfc70`, merge target `main`.
- **Plan:** #21 Phase A (steps 1–6), implementation plan posted on #21
  2026-11-18. Where live evidence disagreed with that plan's shorthand, the
  evidence wins and the deviation is named below.

## Sep 13 baseline → Nov 14 main

Four PRs merged on 2026-11-14, in merge order:

| PR | Merge commit | Change |
|----|--------------|--------|
| #72 | `2ac1bbc` | fix(audit): stop certifying delivery from keywords and status claims |
| #70 | `7010ef1` | docs: adopt repository-specific branch stewardship (`BRANCHES.md`) |
| #71 | `6d39e28` | fix: prevent corpus and docs-audit symlink escape |
| #20 | `019dfc7` | Make learning plans truthful, adaptive, and output-optional |

One PR closed unmerged:

| PR | Closed | Change |
|----|--------|--------|
| #19 | 2026-10-23 | chore(deps): bump the github-actions-deps group (2 updates) |

The Sep 13 bootstrap lease (APS-20260913-01) expired 2026-09-13T23:59Z; its
scope (BRANCHES.md adoption) is done via #70. All further work issues leases
under the adopted `BRANCHES.md`, not under bootstrap grants.

## Wave 0 gate table (verified at `019dfc70`)

| Gate | Issue | Verdict at this head | Evidence |
|------|-------|----------------------|----------|
| CI baseline reproducible | #31 | **Pass** | 9/9 checks success at `019dfc70` (test 3.11/3.12, build, deploy, report-build-status, update_release_draft, stale, Analyze Code (python) x2, Secret Pattern Detection). Re-run locally this run, fresh venv with the CI seed layout (sibling `koinonia-db` at pinned SHA `276b0c1a`): `pytest -q` 145 passed, `ruff check .` clean, `mypy src --ignore-missing-imports` clean (16 files). |
| Privacy classification | #33 | **Planned, not enacted** | #33's plan is posted; its inventory + ADR are not yet built. Admission is still name-based (see #34). |
| Ingest boundary | #34 | **Half done** | Q1 resolved: #71 merged; `corpus.py:88-105` refuses symlinks, `_read_admitted_bytes` uses `O_NOFOLLOW`; 5 boundary tests pass. Q2/Q3 open: no content classification at ingest (a supported-format file with private content in an ordinary directory is still ingested), and no canary sweep beyond discovery. #34 stays open; its build plan is posted. |
| Audit truth | #38 | **Half done** | #72 merged: `_classify_suggestion` returns `"planned"` on both branches, so keyword/status-claim certification is gone (locked by `test_docs_audit.py`). Residue open: the generator still cannot emit `"implemented"` at all, and the committed `docs-audit-report.json` (generated 2026-02-18) carries 58 `"implemented"` labels with no in-tree provenance. #38 stays open; its build plan is posted. |
| Branch constitution | #35 | **Half done** | `BRANCHES.md` adopted via #70 (38 lines at main). Missing: the per-issue ownership table its acceptance requires, and the ref table is stale (dependabot row cites hash `6af9ef796d`, matching no live branch; merged branches `learning/plan-integrity-v2-2026-09-08`, `work/mentor/branch-constitution`, `work/mentor/ingest-boundary` still present with no disposition). #35 stays open; its build plan is posted. |
| Shared toolchain | #32 | **Ownerless — successor named** | PR #19 closed unmerged 2026-10-23; its branch is deleted. Successor: the R1–R3 residue plan posted on #32 (pin `koinonia-db` to `276b0c1a`, exact dev-tool pins, remove CodeQL `continue-on-error`) — the next Wave 0 item, not yet built. Note the ordering inversion: #39 merged before its prerequisite #32; #39's merge does not discharge #32. |
| Plan integrity | #39 | **Verified and closed this run** | PR #20 merged at this head. Both defects verified healed: route-consistent JSON/text encounters and atomic exclusive artifact publication (see the verification table on #39). Residue carried: the ledger-transaction guarantee lives in open #52. |
| Release | #6 / #57 | **Not started** | No tags; releases list holds only draft `v0.0.1` with 0 assets; `pyproject.toml` version is `0.6.0`. Separate packets (#6, #57); not decided here. |

## Deviations from the #21 plan's shorthand

The #21 plan's step 5 named #35, #34, #38, #39 as close-outs "done via"
#70/#71/#72/#20. Each child's own plan, verified at the same head, shows
only #39 is finished:

- #34: Q2/Q3 open — stays open.
- #35: ownership table missing — stays open.
- #38: evidence-contract residue open — stays open.
- #39: verified and closed with its receipt on the issue.

The plan's step 6 named #32's successor as "a fresh Dependabot bump or
manual equivalent". The successor is now the R1–R3 residue plan posted on
#32 itself; that plan is the named successor. One further note for #32's
build: its Sep 13 dev-tool pins are stale — this run's fresh install
resolved `pytest 9.2.0`, `ruff 0.17.6`, `mypy 2.4.1`, so the build must
re-resolve the pins as its plan already requires, and record any
substitution.

## What #21 still needs

- Waves execute in dependency order using the posted loop plans for
  #31–#69 (all planned). Epics #22–#30 have their loop plans posted.
- #21 closes only with the #69 Omega scorecard holding repeatedly, successor
  links attached, and a no-unique-loss verdict. This packet does not close
  #21.
- #21's own "frozen inventory receipt" (Sep 13) is superseded by this file
  on every count: branches, PR states, CI state, and release state have all
  moved since Sep 13.
