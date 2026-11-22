# ADR 005 — Public/private component contract: the minimal public surface and the explicit private interface

- Status: accepted (bounded decision for #42, MTR-008)
- Decided: 2026-11-22, in PR `work/mentor/public-private-contract` (ranked-queue loop)
- Context: #42, implementation plan posted 2026-11-18 (comment 6970377009),
  re-verified live at main `363c7b1c` before building. Parent epic #24,
  control plan #21. Depends on #33 (merged via PR #82) and #34 (merged via
  PR #83) — both landed before this build, so steps 3–5 of the plan proceed.
- Evidence base: live tree at `363c7b1c` (post-#83 merge, 9/9 checks green);
  clean-checkout reproduction in a fresh temp dir (no sibling clone, no
  credentials): `pip install -e '.[dev]'` exit 0, `pytest` 160 passed /
  4 failed / 1 skipped, `ruff check` clean, bare `mypy src` 4 errors,
  `syllabus --help` exit 0; both koinonia-db URLs verified live with
  `--no-cache-dir` (old-org URL redirects; canonical `4444J99` URL works at
  the same pinned commit `3fe455fc`).

## Decision

1. **Q1 — the minimal public surface is the CLI plus the version.**
   Supported: the three entry points `syllabus` / `aps` (`core:cli`) and
   `aps-data-export` (`data_export:main`), plus `__version__`. The
   importable module API is internal: importable, but under no stability
   promise. `__init__.py` declares `__all__ = ["__version__"]` and
   `tests/test_public_surface.py` pins it, so the surface is enforced by a
   test, not by prose. No module is renamed: renaming 14 modules would churn
   every import for no enforcement gain, since Python cannot prevent the
   import anyway — the contract is the declaration plus the test.
2. **Q2 — privately held logic/data is supplied only through explicit
   caller inputs.** Learner profiles, personal corpora, operator
   credentials, and runtime databases are never imported, never read from
   ambient environment, and never embedded: the interface is profile JSON,
   corpus root, and DB path, all caller-supplied. Evidence, now enforced by
   test: no `organvm`/`private` imports in `src/`, no `os.environ`/`getenv`
   use, no hardcoded home-path literals. The per-class rules for the #33
   inventory are in the appendix below.
3. **Q3 — a clean public checkout builds, passes, and runs end to end
   with no sibling clone and no credentials.** The `koinonia-db`
   dependency is pinned to the canonical `4444J99/koinonia-db` URL (same
   commit `3fe455fc`); the README install is `pip install -e '.[dev]'`
   from the public clone alone; the documented end-to-end run uses the
   in-repo synthetic fixture seed (`tests/fixtures/seed`); a new
   `clean-checkout` CI job clones fresh, installs, lints, type-checks,
   tests, and runs the synthetic end-to-end flow. The real seed remains
   available by cloning the canonical repo next to APS (documented as the
   optional step, with the canonical URL).
4. **Tests are hermetic; production defaults are untouched.** The three
   tests that constructed `SyllabusGenerator()` with the sibling default
   now pass the synthetic fixture seed dir; `test_data_export.py` uses the
   fixture and keeps a sibling-present-only test for the real seed
   (skipped otherwise, the `test_ingest_canary.py` pattern). The generator
   and `data_export` default seed dirs are unchanged — the shipped
   `data/sample-learning-paths.json` artifact still regenerates from the
   real seed in CI.

## Alternatives considered, with the counterexample that decides each

- (a) **CLI-only surface vs importable package API vs split repos.**
  An importable API was considered: nothing outside this repo imports the
  package (no external consumer exists in the tree), and the only callers
  are the CLI entry points and the tests. Promising an API nobody uses
  would invent a contract to maintain. Split repos were considered and
  rejected for this PR: there is nothing private in `src/` to split out —
  the grep is clean — so a split would move public code for no boundary
  gain. CLI-only wins: it is the surface that actually ships.
- (b) **Vendor the real seed vs synthetic fixture vs keep the sibling
  requirement.** Vendoring the real seed was considered: it would copy
  third-party content (koinonia-db's taxonomy and reading lists) into this
  repo, duplicating an upstream source of truth and its update burden. The
  counterexample is the fixture itself: the generator needs only the seed
  *shape* (nodes with children, entries with organ tags) to exercise its
  paths, and the real seed is still exercised in CI by the
  sibling-present-only test. Synthetic fixture wins; real seed stays
  upstream, referenced by the canonical URL.
- (c) **Fail loudly on a missing default seed dir vs leave the silent
  empty path.** Failing loudly was considered: a missing seed dir currently
  yields an empty learning path with no error, which is a silent-empty
  failure mode. It is NOT changed here — it is a behavior change outside
  this plan's packaging/docs scope, and the plan's acceptance is the
  clean-checkout reproduction, which passes with the explicit `--seed-dir`.
  The silent-empty behavior is recorded under remaining uncertainty for a
  later MTR item, not silently fixed or silently blessed.
- (d) **Bare `mypy src` vs keep `--ignore-missing-imports`.** Keeping the
  flag was considered: it is what CI ran. The counterexample is that the
  flag ignores missing imports for the whole tree, hiding any future
  untyped dependency, while the only missing imports are the four
  `koinonia_db` modules (no `py.typed` marker upstream). A targeted
  `[[tool.mypy.overrides]]` for `koinonia_db.*` in `pyproject.toml` wins:
  bare `mypy src` now passes and stays strict for everything else.

## Deviations from the plan, decided on live evidence

- The plan's step 1 expected `pip install -e '.[dev]'` to fail without the
  manual sibling clone. It does not: the install succeeds from the public
  clone alone because `koinonia-db` resolves through the old-org git URL,
  which redirects. The defect is narrower than the plan stated: a
  redirect-dependent non-canonical URL, stale README manual steps, four
  tests and bare `mypy` failing without the sibling, and a version drift.
  The fix canonicalizes the URL and removes the manual steps instead of
  inventing a packaging failure that does not exist.
- The plan's step-4 scope said "packaging/docs only". The hermetic test
  change (fixture seed dir in three tests plus one new test file) is the
  mechanism that makes the suite pass on a clean checkout; production
  behavior is unchanged (generator and `data_export` defaults untouched).
  Recorded here so the scope read is explicit, not assumed.
- The plan's step 5 offered "leading-underscore or an `__all__`". The
  build chooses `__all__` (see decision 1) and does not rename modules.
- The plan named the version drift (`pyproject.toml` 0.6.0 vs
  `__init__.__version__` 0.5.0). Fixed in this PR (`__init__` → 0.6.0)
  with a test asserting `pyproject` version, `__version__`, and the
  `syllabus version` output agree, so the drift cannot recur silently.
- The plan's step-1 reproduction included `mypy` (bare). Bare `mypy src`
  fails at the claim head with 4 errors, all `koinonia_db` missing
  `py.typed`. Fixed by the targeted override (decision (d) above), not by
  keeping the CI-wide ignore flag.
- The plan did not anticipate the #33 inventory: the new synthetic fixture
  files (`tests/fixtures/seed/*.json`) match no inventory entry, so the
  classification test (`test_inventory_covers_every_tracked_path_exactly_once`)
  would fail on the PR head. This PR adds the `tests/fixtures/**` public
  entry (29 entries) and moves `verified_at_head` to the base head
  `363c7b1c`, per #33's convention of updating it when the inventory
  changes. The classification test caught this locally in the
  clean-checkout reproduction, before any push.

## Appendix — the #33 inventory consumed (plan step 3)

`docs/privacy-classification.yaml`, verified at head `f8325de8` by #33,
29 entries after this PR's amendment (19 `public`, 7 `private-never-in-git`,
3 `review`): the new `tests/fixtures/**` public entry classifies the
synthetic seed fixture, so every tracked path is still covered by exactly
one entry (the classification test enforces this; the fixture files would
otherwise be unclassified). `verified_at_head` moves to `363c7b1c`, the
base head this PR verified against.

- **public (19):** `src/adaptive_personal_syllabus/*.py`, `tests/*.py`,
  `tests/fixtures/**` (added by this PR, ADR 005),
  `.github/**`, `docs/adr/*.md`, `docs/implementation/**`,
  `docs/pitch/*`, `docs/*.md`, `docs/*.yaml`,
  `docs/source-materials/specs/*`,
  `docs/source-materials/PROVENANCE.yaml`, `docs/syllabusEVOLUTION/*`,
  `data/*.json`, `ecosystem/**`, `*.yaml`, `*.md`, `*.toml`, `LICENSE`,
  `.editorconfig` / `.gitattributes` / `.gitignore`. Interface rule:
  importable or callable from the CLI surface; may live in public git.
- **private-never-in-git (7):** `**/*.db` (+ sqlite variants),
  `**/__pycache__/*` + `*.pyc`/`*.pyo`, `**/*.egg-info` (+ contents),
  `**/.env*`, `**/.private/**` + `**/.secrets/**`,
  `**/.adaptive-syllabus/**`, CI/tool artifacts (`docs-audit-ci.*`,
  `.coverage`, `htmlcov/**`, `**/.pytest_cache/**`, `**/.mypy_cache/**`,
  `**/.ruff_cache/**`). Interface rule: refused at admission by #34's
  `discover_documents` even when name/extension are admissible; never
  tracked; supplied only as explicit caller inputs (profile JSON, corpus
  root, DB path) that live outside git. Enforced by
  `tests/test_public_surface.py::test_private_input_refused_through_cli`,
  which runs the refusal through the CLI.
- **review (3):** `docs/aiChatsThread/*`, `docs/narrative-workbook/*`,
  `docs/source-materials/theory/*`. Interface rule: none — the contract
  does not bless them; rights stay undecided with the owner (ADR 003),
  and no relicense or move is authorized by this PR.

## Observed result (to be filled by CI at the PR head)

- Clean-checkout reproduction re-run green from the public clone alone
  (install, `pytest`, `ruff check`, bare `mypy src`, `syllabus --help`,
  synthetic end-to-end run); the new `clean-checkout` CI job runs the
  same sequence on the PR head.
- `syllabus version` reports the `pyproject.toml` version; the version
  test guards the drift.
- No `organvm`/`private` import, no `os.environ`/`getenv`, no hardcoded
  home path in `src/` (enforced by test, not by grep alone).

## Next step

- #35 (MTR-009): the issue-ownership table in `BRANCHES.md` now has a
  concrete branch to record for #42 (`work/mentor/public-private-contract`,
  base `363c7b1c`, merge target `main`) — and for the merged #33/#34
  branches, whose dispositions the #35 table must resolve.
- #36 (MTR-010): the lease/handoff mechanism's scope values come from
  #35's ownership table and its classification constraints from #33's
  inventory; this contract is the interface it fences.

## Remaining uncertainty

- The generator's silent-empty behavior stands: with no `--seed-dir` and
  no sibling clone, `plan generate` produces a zero-module path with no
  error. A loud failure (or a bundled default seed) is a later MTR item,
  not this PR.
- `koinonia-db` ships no `py.typed` marker, so its API is untyped from
  this repo's side; the override is a workaround, and the upstream gap
  belongs to koinonia-db.
- Main is still unprotected (verified by ADR 003 at its claim head), so
  the guard workflows are CI-advisory only; protection and rulesets are
  the owner's action.
- The rights status of model outputs and personal guides stays `review`
  until the owner decides (ADR 003).
