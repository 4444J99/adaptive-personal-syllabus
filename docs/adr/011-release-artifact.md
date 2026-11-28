# ADR 011 — Release artifact: a GitHub release a stranger can install and verify

- Status: accepted (bounded decision for #57, MTR-026)
- Decided: 2026-11-28, in PR `work/mentor/release-artifact` (ranked-queue loop)
- Context: #57, implementation plan posted 2026-11-18 (comment 6988417467),
  re-verified live at main `24ec976c` before building. Parent epic #6,
  control plan #21. Depends on #53 (ADR 008, merged via PR #96), whose
  outcome this decision consumes: the version the artifact carries is
  0.6.0, derived from installed distribution metadata, and `syllabus
  version` prints it. Depends on #34 (merged via PR #83). #43 (MTR-012,
  repo layout) is still planned and does not gate this delivery: the new
  files follow the existing layout.
- Evidence base: live tree at `24ec976c` (post-#99 merge, 0 open PRs),
  verified through the GitHub API and a source-tarball read. Neither
  `adaptive-personal-syllabus` nor `koinonia-db` exists on PyPI (both
  lookups return `{"message": "Not Found"}`). No workflow runs
  `python -m build`; no wheel or sdist is ever produced. GitHub has zero
  tags and exactly one release: `v0.0.1`, a draft, 0 assets. `koinonia-db`
  is pinned in `pyproject.toml` to its main head
  `3fe455fcbdeca98ab209f38a6b892dc29217c6a1` (verified live: the pin equals
  the `4444J99/koinonia-db` main head, and CI checks out the same commit);
  the koinonia-db repo is archived. CI's clean-checkout job already proves
  a from-clone install with no sibling clone and no credentials (#42 Q3
  guard).

## Decision 1 — The artifact is a GitHub release: wheel + sdist + SHA256SUMS + dependency bill

The 0.6.0 release is published as a GitHub release carrying four items:
the wheel, the sdist, a `SHA256SUMS` file with the SHA-256 of each
distributed file, and a `DEPENDENCY-BILL.txt` with the exact resolved
versions (`pip freeze` captured in the release job). The release notes
name the source commit, the CI run that built the artifact, the
compatibility promise (ADR 008), and the rollback procedure (Decision 4).
Reasoning: this is the only option that makes a versioned artifact
verifiable by checksum without needing a registry for the archived
`koinonia-db` dependency. The release workflow (`.github/workflows/
release.yml`) is the authorized rail: it publishes only when a `v*` tag
is pushed, so the tag stays the owner's call (ADR 008 Decision 8) and
nothing in this PR publishes anything.

## Decision 2 — PyPI is rejected for 0.6.0

A PyPI wheel+sdist pair cannot install: `koinonia-db` is archived and unpublished,
so the dependency cannot resolve from PyPI, and APS's own
`pyproject.toml` would fail dependency resolution for any installer.
Publishing `koinonia-db` first would need unarchiving that repo (his
call) plus trusted-publisher provisioning (his). Reasoning: a published
artifact that cannot install is worse than no artifact — it advertises a
promise the install cannot keep. If koinonia-db is ever published, this
decision is revisited with the registry evidence in hand, not before.

## Decision 3 — A pinned source install alone is not the artifact

The pinned source install already exists and is proven by CI's
clean-checkout job (`pip install -e .[dev]` from the public clone alone,
synthetic end-to-end run, no credentials). Reasoning: it is not a
versioned artifact — there is nothing for a stranger to checksum against
a published value, so "artifact matches tested commit/version" cannot
hold. The source install stays the developer path; the release is the
stranger path. `docs/QUICKSTART.md` documents the stranger path only.

## Decision 4 — Rollback follows ADR 008 Decision 6

A bad release is rolled back by publishing a patch release that reverts
the change; tags are never moved and published versions are never
re-tagged. A database opened by a newer version is not opened by older
code, so a rollback that touches the store shape ships with a forward
migration back, never a downgrade. Reasoning: ADR 008 already decided
this; inventing a second rollback procedure for the same release would
split the truth. The release notes point at ADR 008 instead of restating
it.

## Decision 5 — Reproducibility is checked, not asserted

The release workflow builds the wheel and sdist twice with
`SOURCE_DATE_EPOCH` set from the tagged commit's timestamp and fails the
job if the wheel bytes differ or the sdist member contents differ. What
"reproducible" means here is precise, because the evidence forced it:
the wheel is byte-identical across builds, but the sdist is only
content-identical — setuptools does not normalize sdist tar member
mtimes from `SOURCE_DATE_EPOCH` (verified at main `24ec976c`: two builds
from the same tree, wheel SHA-256 equal, all 67 sdist members equal in
name and bytes, 15 envelope mtimes differing). So the check compares
wheel hashes and sdist member content hashes, not raw `.tar.gz` bytes.
Reasoning: "artifact matches tested commit/version" is only checkable
when the same commit always produces the same artifact contents; the
published `SHA256SUMS` binds the published bytes, and a rebuild verifies
those contents. The check runs on every pull request touching the release
inputs, so a non-reproducible build fails before merge, not at release
time.

## Decision 6 — What this PR does and does not do

This PR delivers the release workflow, this decision, the quick-start,
the clean-room receipt, and the contract tests. It does not create tag
`v0.6.0`, does not delete or retarget the `v0.0.1` draft release, and
does not publish to PyPI — all owner steps (ADR 008 Decision 8). Issue
#6 closes only after the delivered verification exists: the tagged
release plus its receipt. A plan, draft PR, or checklist is not delivery.

## What was verified, what was not

- Verified: both PyPI absences; the absence of any build/publish step;
  zero tags and the single `v0.0.1` draft (0 assets); the koinonia-db
  pin equals the koinonia-db main head; the clean-room run in
  `docs/implementation/release-verification-0.6.0.md` (wheel built from
  this PR's head, installed in a fresh venv with no checkout, checksum
  verified, `syllabus version` prints 0.6.0, one full generate→show cycle
  against the sample corpus, dependency bill captured, no credentials,
  no private service).
- Not verified (out of scope for this PR): whether the release job's
  `gh release create` succeeds under the repo's `GITHUB_TOKEN`
  permissions — it runs only on a tag push, which is the owner's step,
  so the first run is observed then, not simulated now; whether
  release-drafter would draft a different starting version if the
  `v0.0.1` draft were deleted (ADR 008 already records this as unknown,
  and the owner sets the tag to `v0.6.0` explicitly).
