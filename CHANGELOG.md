# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `docs/mentor-roadmap-state.md` — Sep 13 baseline → Nov 14 main reconciliation receipt for the #21 control plan: the four-PR merge wave (#70, #71, #72, #20), PR #19 closed unmerged, and a Wave 0 gate table with a verdict per gate at main `019dfc70` (#39 verified and closed; #34, #35, #38 half done with their own build plans; #32 ownerless with its R1–R3 successor plan named)

### Changed
- #21's Sep 13 "frozen inventory receipt" is superseded by `docs/mentor-roadmap-state.md` on every count (branches, PR states, CI state, release state)

## [0.6.0] - 2026-02-24

### Added
- `data_export` module — generates `data/sample-learning-paths.json` with 3 sample paths (beginner/intermediate/advanced)
- `aps-data-export` CLI entry point
- 4 new tests in `tests/test_data_export.py`
- Produce edge fulfilled: `learning_path` (json+text)

## [0.5.0] - 2026-02-18

### Added
- Snapshot-scoped corpus storage model with persistent multi-snapshot history (`documents.snapshot_id`)
- Snapshot selectors for `syllabus corpus stats` (`--snapshot-id`, `--snapshot-name`)
- Determinism inputs in plan JSON output (`snapshot_id`, evidence hash set, personalization-rules hash)
- `aps` CLI alias to preserve compatibility with existing command examples
- YAML validation in corpus ingest (`yaml.safe_load`) with deterministic malformed-file errors
- Additional tests for multi-snapshot ingest lifecycle, snapshot-filtered stats, malformed YAML, and snapshot-sensitive plan IDs

### Changed
- Corpus ingest is now atomic and non-destructive; prior snapshots remain queryable
- Ingest write-path now batches inserts in a single transaction per run (documents, aliases, chunks, ledger event)
- Plan persistence now records `snapshot_id` in `plans`
- CI workflow hardened to enforce lint, mypy, pytest, and CLI smoke checks
- README updated to separate roadmap-only `aps` flows from implemented `syllabus` flows and corrected CI workflow references
- Package version advanced to `0.5.0`

### Fixed
- Provenance reproducibility gap caused by corpus reset behavior between ingests
- Command and workflow documentation drift (`ci-python.yml` references, contradictory badges)

## [0.4.1] - 2026-02-18

### Added
- Local-first SQLite storage layer at `~/.adaptive-syllabus/adaptive_syllabus.db` with schema for documents, aliases, chunks, profiles, plans, hook runs, ledger events, and snapshots
- Corpus ingestion service with deterministic deduplication, canonical/alias tracking, and heading-aware chunking
- Append-only hash-chain ledger service with integrity verification (`syllabus ledger verify`)
- Profile-aware planning service that merges learner profile + corpus evidence + module generation into a stable JSON plan schema
- Chamber hook interface (`ChamberHook`) and default no-op AAW/character-node registry
- New CLI command groups:
  - `syllabus corpus ingest --root <path> --snapshot <name>`
  - `syllabus corpus stats`
  - `syllabus ledger verify`
  - `syllabus profile init --name ... --goals ... --context ...`
  - `syllabus plan generate --profile <path> --format text|json|md`
  - `syllabus chamber run --hook <name> --dry-run`
- New test coverage for corpus ingestion, ledger verification/tamper detection, deterministic planning, and new CLI flows

### Changed
- Expanded domain models with new dataclasses: `DocumentRecord`, `DocumentChunk`, `LedgerEvent`, `CorpusSnapshot`, `ChamberHookSpec`, `CharacterNodeSpec`, and `PersonalizationRule`

## [0.4.0] - 2026-02-17

### Added
- **AQUA COMMUNIS sprint** — CLI and DB generator test coverage
- `tests/test_db_generator.py` — 5 tests: URL normalization, passthrough, psycopg, empty taxonomy, data build
- `tests/test_cli.py` — 5 tests: version, text/json/md format, missing organs error
- Test count: 9 → 19 (+10)

## [0.3.0] - 2026-02-17

### Added
- `DatabaseSyllabusGenerator` — reads taxonomy/readings from Neon DB and persists generated paths
- Syllabus schema models: `LearnerProfileRow`, `LearningPathRow`, `LearningModuleRow`
- Database persistence for generated learning paths

## [0.2.0] - 2026-02-17

### Added

- `__main__.py` for `python -m adaptive_personal_syllabus` support
- `total_modules` field on LearnerProfile for accurate progress tracking

### Fixed

- Generator now filters readings per child topic instead of giving every child the same readings
- Progress percentage now based on actual module count (not arbitrary 10x multiplier)

## [0.1.1] - 2026-02-13

### Added

- CONVERGENCE Sprint: Full PRODUCTION promotion — CI/CD, prototype skeleton, ADRs, badge row
- Provenance materials deployed from local source archive

## [0.1.0] - 2026-02-13

### Added

- Initial public release as part of the organvm eight-organ system
- Core project structure and documentation
- README with portfolio-quality documentation

[Unreleased]: https://github.com/organvm-vi-koinonia/adaptive-personal-syllabus/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/organvm-vi-koinonia/adaptive-personal-syllabus/compare/v0.4.0...v0.5.0
[0.4.1]: https://github.com/organvm-vi-koinonia/adaptive-personal-syllabus/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/organvm-vi-koinonia/adaptive-personal-syllabus/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/organvm-vi-koinonia/adaptive-personal-syllabus/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/organvm-vi-koinonia/adaptive-personal-syllabus/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/organvm-vi-koinonia/adaptive-personal-syllabus/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/organvm-vi-koinonia/adaptive-personal-syllabus/releases/tag/v0.1.0
