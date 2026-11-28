# Release verification receipt — 0.6.0 clean-room run (APS #57)

Run 2026-11-28 by ranked-queue-build (02:15 EST run) against the
`work/mentor/release-artifact` work tree at base `24ec976c` (main head
after the PR #99 merge). This is the receipt for the procedure in
`docs/QUICKSTART.md`, run before the release exists: the wheel and sdist
below were built from this PR's work tree, not from a tagged release.
The release workflow's `build` job re-verifies the same steps in CI at
the PR head and again at the merge head; the tag itself (`v0.6.0`) is the
owner's call (ADR 008 Decision 8).

## Build and reproducibility

- `SOURCE_DATE_EPOCH=1795845182` (base commit time `2026-11-28T05:53:02Z`).
- Built twice with `python -m build`:
  - Wheel `adaptive_personal_syllabus-0.6.0-py3-none-any.whl` —
    byte-identical across both builds.
  - Sdist `adaptive_personal_syllabus-0.6.0.tar.gz` — content-identical
    across both builds (67 members, same names and bytes); the raw
    `.tar.gz` bytes differ in tar envelope mtimes only, because setuptools
    does not normalize sdist member mtimes from `SOURCE_DATE_EPOCH`
    (ADR 011 Decision 5).
- SHA-256 of the built artifacts (this work tree):
  - Wheel: `fbb1cf76929d1ebd4590ee0347c8e4c63877f441de338146cd0621bc4650d884`
  - Sdist: `08ab8b7ab4be25ad76a02838d789bdace9b71beae1a307088ff34c3e91fc3205`
- `sha256sum -c SHA256SUMS`: both lines `OK`.
- The sdist carries the sample seed at
  `adaptive_personal_syllabus-0.6.0/tests/fixtures/seed/` (both
  `taxonomy.json` and `reading_lists.json`), via `MANIFEST.in`.

## Clean-room install (fresh venv, no checkout)

- `python -m venv`, `pip install ./adaptive_personal_syllabus-0.6.0-py3-none-any.whl`
  — no checkout, no sibling clone, no credential, no private service.
- `syllabus version` prints `adaptive-personal-syllabus v0.6.0`.
- Full loop against the sample corpus (seed extracted from the sdist,
  one-note corpus created fresh):
  - `syllabus corpus ingest --root ./my-notes --snapshot quickstart`
  - `syllabus profile init --name Learner --organs I --purpose evaluate --phone-only`
  - `syllabus plan generate --profile ./profile.json --seed-dir <sdist seed> --format json`
  - `syllabus plan show 1 --format md` — prints the generated plan
    (Synthetic Systems / Synthetic Ontology readings listed).
  - `syllabus plan encounter 1` — shows the first encounter step
    (Synthetic Systems, phone route, worked-explanation route).

## Dependency bill (pip freeze, fresh install of the wheel)

```text
adaptive-personal-syllabus @ file:///.../adaptive_personal_syllabus-0.6.0-py3-none-any.whl#sha256=fbb1cf76929d1ebd4590ee0347c8e4c63877f441de338146cd0621bc4650d884
alembic==1.20.1
click==8.5.1
greenlet==3.5.6
koinonia-db @ git+https://github.com/4444J99/koinonia-db.git@3fe455fcbdeca98ab209f38a6b892dc29217c6a1
Mako==1.4.3
MarkupSafe==3.0.4
psycopg==3.3.9
psycopg-binary==3.3.9
psycopg-pool==3.3.3
PyYAML==6.0.4
SQLAlchemy==2.1.9
typing_extensions==4.16.0
```

## External services touched

- PyPI: `click`, `PyYAML`, `sqlalchemy` and their transitive dependencies
  (above). GitHub: the `koinonia-db` git URL (pinned commit above) and
  the source tarball used to verify the base. Nothing else. No private
  service, no credential, no personal archive was needed at any step.

## What this receipt does not prove

- The release itself does not exist yet: no tag `v0.6.0` has been pushed
  and the `v0.0.1` draft is untouched (both owner steps). The hashes above
  are for artifacts built from this PR's work tree; the release
  workflow rebuilds from the merge head and publishes that build's
  checksums, so the published `SHA256SUMS` will differ from the values
  here.
- The release job's `gh release create` step has not run (it runs only
  on a tag push); its first run is observed when the owner pushes the tag.
