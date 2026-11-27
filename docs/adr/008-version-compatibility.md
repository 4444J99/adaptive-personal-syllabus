# ADR 008 — Version compatibility: one version, one promise, one source per schema

- Status: accepted (bounded decision for #53, MTR-025)
- Decided: 2026-11-27, in PR `work/mentor/version-contract` (ranked-queue loop)
- Context: #53, implementation plan posted 2026-11-18 (comment 6987977925),
  re-verified live at main `9c3243f1` before building. Parent epic #22,
  control plan #21. Depends on #42 (ADR 005, merged via PR #84), whose
  outcome this decision consumes: the public surface is already fixed, and
  the version mismatch the plan assumed was already reconciled there.
- Evidence base: live tree at `9c3243f1` (post-#95 merge, 0 open PRs),
  verified through the GitHub API and a source-tarball read. `__version__`
  is `"0.6.0"`, equal to `pyproject.toml` `0.6.0` and CHANGELOG `[0.6.0]`
  (the 0.5.0 runtime string the plan describes is gone — #42's PR #84,
  commit `fc5a41ef`, set the literal to 0.6.0). GitHub has zero tags and
  exactly one release: `v0.0.1`, a draft (id 299563311, created
  2026-03-20, never published). The draft is auto-maintained, not
  abandoned: release-drafter updated it `2026-11-27T22:06:26Z`, 13 seconds
  after the #95 merge, and its body states no previous published release
  exists, so it cannot resolve a next version and keeps `v0.0.1`.
  `schema_version` literals were enumerated across the tree before this
  change: plan JSON `"2.0"`, encounter `"1.2"`, CLI envelopes `"1.0"`,
  profile `"1.0"`, audit report `"2.0"`, milestone execution plan `"1.0"`,
  fingerprint int `2`, source-selection int `1`, legacy projection
  `"legacy_projection"` — eight values in six files, no documented rule
  for when any of them changes. The SQLite store had no schema marker at
  all (`CREATE TABLE IF NOT EXISTS` throughout `storage.py`, no
  `PRAGMA user_version`). No compatibility, versioning, or migration
  document existed anywhere in the tree.

## Decision 1 — One authoritative version: 0.6.0

`pyproject.toml`, CHANGELOG, and the runtime now agree on `0.6.0`, and
`__version__` is derived from the installed distribution metadata via
`importlib.metadata` instead of a second literal. Reasoning: the plan
offered exactly this alternative ("derive it from installed package
metadata via `importlib.metadata` and delete the literal"), and CI
installs with `pip install -e .[dev]`, so metadata is available wherever
the package runs as installed. The literal survives only as a
source-checkout fallback (`_FALLBACK_VERSION`), and
`tests/test_compatibility.py` pins it to the pyproject version, so it
cannot drift silently. `syllabus version` prints the derived version.

## Decision 2 — The contract inventory (the matrix's rows)

The interfaces a user or downstream tool may depend on, verified at
`9c3243f1`. Anything not listed here is internal and carries no promise
(ADR 005 already fixes the module API as internal).

| Interface | Current version | Where it lives |
| --- | --- | --- |
| Package version | 0.6.0 | `pyproject.toml`, `__version__` (metadata-derived) |
| CLI entry points | — | `syllabus` / `aps` → `core:cli`, `aps-data-export` → `data_export:main` |
| CLI commands | — | `generate`, `version`; `corpus ingest/refresh/stats/passage/admit/revoke/judge/support`; `ledger verify`; `profile init`; `plan generate/show/encounter/artifact/authorize-publication`; `chamber run`; `docs audit/execute-milestone` |
| Plan JSON | 2.0 | `planner.py` (`PLAN_SCHEMA_VERSION`) |
| Learner profile document | 1.0 | `core.py` (`PROFILE_SCHEMA_VERSION`) |
| Encounter decision | 1.2 | `encounter.py` (`ENCOUNTER_SCHEMA_VERSION`) |
| CLI JSON envelopes | 1.0 | `core.py` / `corpus.py` / `storage.py` (`CLI_ENVELOPE_SCHEMA_VERSION`) |
| Docs-audit report | 2.0 | `docs_audit.py` (`AUDIT_REPORT_SCHEMA_VERSION`) |
| Milestone execution plan | 1.0 | `docs_audit.py` (`MILESTONE_EXECUTION_PLAN_SCHEMA_VERSION`) |
| Plan fingerprint | int 2 | `planner.py` (`FINGERPRINT_SCHEMA_VERSION`, pre-existing) |
| Source selection | int 1 | `planner.py` (`SOURCE_SELECTION_SCHEMA_VERSION`, pre-existing) |
| Legacy plan projection | marker | `storage.py` (`LEGACY_PROJECTION_SCHEMA_VERSION`; read-only, never bumps) |
| SQLite store | 1 | `storage.py` `schema_meta` table (`DB_SCHEMA_VERSION`) |
| Ledger event / hash chain | unversioned | `ledger.py` (prev_hash → event_hash chain + payload_json) |
| Lesson schema | unversioned | `lesson_schema.py` declares `schema_version: str`, but no code ever assigns it — no lesson document carries a version today |
| `data_export` sample JSON | unversioned | `data/sample-learning-paths.json` carries no version field |

Every `schema_version` literal now lives in exactly one place,
`src/adaptive_personal_syllabus/versions.py`, and every emitter imports
its constant from there. Reasoning: the drift that produced this issue
was a literal in one file disagreeing with a literal in another; a
single module makes the next disagreement a one-line diff in one file,
and the compatibility tests pin the emitted values so a silent change
fails CI.

## Decision 3 — SemVer for the 0.x line

Breaking (requires a minor bump on the 0.x line, a deprecation window,
and a migration note): removing or renaming a CLI command or flag;
removing or renaming a plan-schema, profile, encounter, envelope, or
audit-report field; changing the ledger event format; changing the
database shape without an upgrade path; bumping any schema version
without the migration note that explains the change.

Non-breaking (patch): additive fields, new commands, new optional
flags, additive tables or columns, new values in an existing enum that
old readers ignore. Reasoning: the 0.x line has no stability promise
beyond this document, so the minor version is the breaking boundary
until 1.0 — and the boundary is only meaningful if additive change is
explicitly free, or every addition becomes a negotiation.

## Decision 4 — Deprecation window

A breaking change ships first as a deprecation: the old name or shape
keeps working for one minor release, with a warning on the CLI path
that uses it and a CHANGELOG notice naming the removal release.
Removal happens only in the named minor release. Reasoning: nothing has
ever been published, so the first real consumers arrive after this
document; the window protects them from the second release, not the
first, and a window of one minor is short enough to actually enforce.

## Decision 5 — Migration procedure

- Plan JSON: readers accept every schema version they understand.
  `Storage.get_plan` reads stored payloads verbatim (`json.loads`, no
  version rejection), and the legacy projection path keeps pre-payload
  plans readable. A bump ships with a migration note in CHANGELOG and a
  fixture in `tests/fixtures/` proving the previous shape still reads —
  `plan-0.5.0-era.json` (schema `"1.0"`, shape verified against the
  0.5.0-era `planner.py` at commit `9e1706d9`) is the first such fixture.
  Reasoning: the only 0.5.0-era artifacts that can exist are local
  databases and exported plan JSONs, never published releases, so
  reader tolerance plus a fixture is the whole migration — there is
  nothing to re-tag and no hosted data to move.
- SQLite store: `schema_meta` carries the store version (1, stamped on
  first open of a pre-marker database, which has exactly the version-1
  shape). A bump adds a migration in `Storage._run_migrations` and
  increments `DB_SCHEMA_VERSION`. A database whose marker is newer than
  the running code refuses to open with both versions named — forward
  only, never a silent downgrade. Reasoning: the marker is the first
  migration's detection mechanism, which is what the plan asked for;
  refusing a newer database is the only safe answer when the reader
  cannot know what the newer writer changed.

## Decision 6 — Rollback procedure

A bad release is rolled back by publishing a patch release that reverts
the change; tags are never moved and published versions are never
re-tagged. A database opened by a newer version is not opened by older
code (Decision 5's guard), so a rollback that touches the store shape
ships with a forward migration back, never a downgrade. Reasoning: with
no releases ever published, the procedure is written before it is
needed; the no-retag rule is cheap to state now and expensive to
recover after the first publish.

## Decision 7 — The 1.0 exit gate

The package moves to 1.0 when all four hold: (a) a 0.6.0 release is
published with this promise in force; (b) one full minor cycle ships
with zero breaking changes outside the deprecation window; (c)
migration fixtures pass for every schema version ever published; (d)
the contract inventory above is verified against the release tag.
Reasoning: the issue asks for an explicit gate, and a gate made of
evidence (a published release, a clean minor cycle, passing fixtures,
a verified inventory) can be checked at the release, unlike a gate
made of intentions.

## Decision 8 — Release mechanics (what this PR does and does not do)

This PR delivers Decisions 1–7 as code, tests, and this document. It
does not delete the stale `v0.0.1` draft release and does not create
the `v0.6.0` tag, because both are repo writes outside the executor's
standing go and the tag must be at the merge head, which does not exist
until this PR merges. The owner steps, in order, are: (1) delete the
`v0.0.1` draft (release id 299563311), or edit its tag to `v0.6.0` —
release-drafter cannot self-correct it, because with no published
baseline it warns and keeps `v0.0.1`; (2) after this PR merges and CI
is green at the merge head, tag `v0.6.0` at that head; (3) verify the
tag, the draft release state, and the CHANGELOG entry agree, and record
the 1.0 exit gate from Decision 7 in the release notes. Reasoning: the
tag is the moment the promise becomes public and binding, so it must
not precede the green checks or the document — and the draft must not
be left to be published by accident at the wrong version.

## What was verified, what was not

- Verified: the version reconciliation (all three sources read 0.6.0 at
  `9c3243f1`); the release/draft state (zero tags, one draft, updated
  2026-11-27T22:06:26Z by release-drafter); every schema-version site
  in the tree; the absence of a DB marker; the absence of any
  compatibility document.
- Not verified (out of scope for this PR): whether release-drafter
  would draft `v0.1.0` or another starting version if the `v0.0.1`
  draft were deleted — its own body text says only that the draft is
  a manual starting point to review before publishing, so this ADR
  does not assert a version it cannot evidence; the owner sets the
  tag to `v0.6.0` explicitly in Decision 8.
