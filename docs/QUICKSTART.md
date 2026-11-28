# Quick-start: install the versioned release and verify it

Install `adaptive-personal-syllabus` 0.6.0 from its GitHub release and
prove it works — no checkout, no neighbour clone, no credentials, no
private service. The release is published when the owner pushes tag
`v0.6.0` (ADR 008 Decision 8); until then there is no release to install
from, and the receipt in
`docs/implementation/release-verification-0.6.0.md` records the same
procedure run against the wheel built from the release PR's head.

## 1. Download the release

From
`https://github.com/4444J99/adaptive-personal-syllabus/releases/tag/v0.6.0`,
download:

- `adaptive_personal_syllabus-0.6.0-py3-none-any.whl`
- `adaptive-personal-syllabus-0.6.0.tar.gz`
- `SHA256SUMS`
- `DEPENDENCY-BILL.txt` (the exact resolved versions from a fresh install
  of this wheel — read it to reproduce the install)

## 2. Verify the checksums

```sh
sha256sum -c SHA256SUMS
```

Both lines must report `OK`. If either fails, stop: the download does
not match the published artifact.

## 3. Install the wheel in a fresh virtual environment

```sh
python3 -m venv aps-venv
aps-venv/bin/python -m pip install --upgrade pip
aps-venv/bin/python -m pip install ./adaptive_personal_syllabus-0.6.0-py3-none-any.whl
```

The install resolves `click`, `PyYAML`, and `sqlalchemy` from PyPI and
`koinonia-db` from its pinned git URL (`4444J99/koinonia-db`, commit
`3fe455fcbdeca98ab209f38a6b892dc29217c6a1`). No other network access, no
credential, and no private service is needed; if any step asks for one,
the install is not the published path — stop and report it.

## 4. Check the version

```sh
aps-venv/bin/syllabus version
```

It prints `adaptive-personal-syllabus v0.6.0`. Any other version means the
wheel is not the 0.6.0 release.

## 5. Run one full loop against the sample corpus

The sample corpus ships inside the sdist, so no checkout is needed:

```sh
tar xzf adaptive-personal-syllabus-0.6.0.tar.gz \
  adaptive-personal-syllabus-0.6.0/tests/fixtures/seed
mkdir -p my-notes
cat > my-notes/note.md <<'EOF'
# A first note

Learning is a loop: read, try, reflect, and let the next step follow
from evidence rather than from a score.
EOF
aps-venv/bin/syllabus corpus ingest --root ./my-notes --snapshot quickstart --db-path ./quickstart.db
aps-venv/bin/syllabus profile init --name Learner --organs I --purpose evaluate --phone-only --output ./profile.json --db-path ./quickstart.db
aps-venv/bin/syllabus plan generate --profile ./profile.json --seed-dir ./adaptive-personal-syllabus-0.6.0/tests/fixtures/seed --format json --db-path ./quickstart.db
aps-venv/bin/syllabus plan show 1 --format md --db-path ./quickstart.db
aps-venv/bin/syllabus plan encounter 1 --db-path ./quickstart.db
```

`plan show` prints the generated plan and `plan encounter` shows its
first encounter step. The seed is synthetic fixture content (invented
topics only, never real seed data); for real seed content, clone the
canonical `koinonia-db` repo and pass its seed directory instead.

## What you need, and what you do not

- Needed: Python 3.11+, network access to GitHub (the release and the
  `koinonia-db` git URL) and PyPI (the remaining dependencies).
- Not needed: a checkout of this repo, a sibling `koinonia-db` clone, any
  credential, any private service, or any personal archive. Profiles,
  databases, reading histories, and responses stay private and outside
  version control.

## If a release goes wrong

Rollback is a patch release that reverts the change; tags are never
moved and published versions are never re-tagged (ADR 008 Decision 6).
The compatibility promise the release carries is ADR 008
(`docs/adr/008-version-compatibility.md`).
