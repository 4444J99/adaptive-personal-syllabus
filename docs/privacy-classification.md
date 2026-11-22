# Privacy classification — adaptive-personal-syllabus #33 (MTR-006)

**Status of this plan:** This is one take, not a solidified plan. It is my
current version of what I think should work, based on the source verified at
the head named in the plan, and it needs further investigation and further
hardening before and during implementation. Each step includes my reasoning
for why, so the plan can be checked rather than trusted; where live evidence
disagrees with the plan, the evidence wins and the plan gets revised.

The classification inventory is `docs/privacy-classification.yaml`: every
tracked path is covered by exactly one entry in one of three classes —
`public` (may live in public git), `private-never-in-git` (must never be
tracked), `review` (rights or exposure uncertain; stays unresolved, never
silently relicensed or moved). Decisions are recorded in
`docs/adr/003-privacy-classification.md`. Enforcement is
`tests/test_privacy_classification.py`, run by the Python CI suite and by the
privacy-classification guard workflow on every PR head.

## What changed in this PR (the #33 build)

- The tracked runtime database (`.adaptive_syllabus_docs_audit.db`) and the
  tracked build outputs (`src/adaptive_personal_syllabus.egg-info/*`) are
  untracked. No code in the repo references the database filename — it was
  an orphan artifact — and the runtime database default lives in the owner's
  home runtime directory (`storage.py` `DEFAULT_DATA_DIR`); the audit
  database is reproducible on demand via `syllabus docs audit --db-path`.
  Tracked `__pycache__`/`*.pyc` files were already dropped by merged #80.
- `.gitignore` now covers every forbidden class, so the same paths cannot be
  committed again.
- Absolute home-directory paths were removed from all four tracked files
  that carried them: `docs/source-materials/PROVENANCE.yaml` (39 source
  paths, redacted to repo-relative paths — provenance by hash survives),
  `docs/implementation/docs-audit-report.json` and
  `docs/implementation/docs-audit-roadmap.md` (one stale audit-run root
  path each, redacted to the repo-relative audited tree), and
  `docs/seed.yaml` (one knowledge-graph database path, rewritten in portable
  home-relative form).
- The AI-chat transcripts (`docs/aiChatsThread/`), personal writing guides
  (`docs/narrative-workbook/`), and their duplicates
  (`docs/source-materials/theory/`) stay `review`: kept, not moved, not
  relicensed. The rights decision on model outputs and personal guides is
  the owner's, and this PR does not take it.
- The two preservation branches (`capture/main-heal-2026-07-02T13-14-42Z`,
  `wip/preserve-2026-05-31-adaptive-personal-syllabus`) are classified
  `review`: each unique hunk is classified before any extraction; nothing is
  extracted unclassified. No branch was touched by this PR.

## Private custody receipt (counts and classes only)

What lives outside public git: the live runtime database (1 database, the
default runtime location named by `storage.py`), the reproducible audit
database (1 database, regenerable on demand — no stored copy is kept), and
the two preservation branches (2 branches, classified `review`, custody per
`BRANCHES.md`). No private path or content is recorded here.

## History review (sanitized receipt only)

Scoped 2026-11-21: 3 incidents (`db66c96` #14 session artifacts, `0fa627b`
#15 mis-classified transcript, `3ba1c28` #76 third-party transcript). The
review of whether anything from those incidents persists in history, and
whether rotation or notification is owed, is a private-channel item per
`SECURITY.md` — it is not recorded in public text, and no history was
rewritten by this PR.

## What this guard is not

Main is unprotected (verified at the claim head: `protected: false`, no
protection, no rulesets), so the guard workflow and the classification test
are CI-advisory only: a direct push can still bypass them. Branch
protection and rulesets are the owner's action, not this PR's. The guard
fails a PR that adds a forbidden path or an unclassified path; it does not
pretend to enforce anything on a direct push.

## Dependency revision (#33 unblocks #34 and #42)

- #34 (MTR-007, classification-aware admission): next step is to consume
  this inventory in `discover_documents`/`allowed()` so a file classified
  private is refused at discovery even when its name and extension are
  otherwise admissible.
- #42 (MTR-008, public/private component contract): next step is to write
  the component contract against this inventory.
