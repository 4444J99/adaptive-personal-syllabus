# Adaptive Personal Syllabus

APS is a local, deterministic learning-plan generator. It uses selected interests and seed topics, records corpus provenance, and offers optional encounters. Basic generation needs no cloud-model credential.

## What runs today

- Corpus ingestion preserves snapshots, content identities, aliases and text chunks. Binary PDF/DOCX files are registered but not text-extracted.
- Plans carry a versioned full SHA-256 fingerprint and a compatible 12-character display ID.
- SQLite stores the complete plan atomically. `plan show` retrieves it after restart.
- Encounter instructions respond to selected purpose, matching task observations, prerequisites, medium and access conditions. Reading history does not establish ability.
- Source retrieval returns lexical candidates, never automatic evidence. Passage inspection and attributed claim judgments are separate commands; contradictions remain visible.
- Wings are optional descriptors. `plan artifact` can explicitly generate one selected Wing's assistant-authored working sheet. It does not create a finished essay or write in the learner's voice.
- Publication authorization is a separate, exact-file receipt. APS has no publication transport. Authorization is not publication.

Understanding, enjoyment, a better question or a useful action may complete an encounter. No test, essay, public artifact or eight-Wing output is required.

## Install and run

Python 3.11 or newer is required. From this checkout, install the existing seed-data dependency next to APS:

```sh
git clone https://github.com/organvm-vi-koinonia/koinonia-db.git ../koinonia-db
pip install ../koinonia-db
pip install -e '.[dev]'
syllabus corpus ingest --root ./docs --snapshot local-docs --db-path ./local.db
syllabus profile init --name Learner --organs I --purpose evaluate --phone-only --output ./profile.json --db-path ./local.db
syllabus plan generate --profile ./profile.json --seed-dir ../koinonia-db/seed --format json --db-path ./local.db
syllabus plan show 1 --format md --db-path ./local.db
```

Keep profiles, databases, reading histories and responses private and outside version control. The default level is `unassessed`; a chosen difficulty is a configuration preference, not a competence score. Existing organ topics are software options, not a compulsory personal syllabus.

`profile init --wing academic --wing wiki` selects exactly those optional descriptors. Omit `--wing` for an encounter-only plan. Valid IDs: `academic`, `sop`, `business`, `social`, `community`, `wiki`, `web_blog`, `grants`. Invalid IDs fail with a user-facing error.

```sh
syllabus plan artifact 1 --wing academic --output ./academic-v1.md --db-path ./local.db
# Only when you actually authorize these bytes and this destination:
syllabus plan authorize-publication ./academic-v1.md --destination 'chosen destination' --authorize --db-path ./local.db
```

The second command records consent only; neither command publishes. A changed file needs fresh authorization. Generated working sheets label assistant instructions and leave learner words unsupplied.

Use an existing writable directory for `--output`. Artifact generation refuses to overwrite an existing file. A Wing descriptor in a plan is only an option; a working sheet exists only after `plan artifact` successfully writes it.

To open only one encounter on a phone, or request its explanation without an assessment:

```sh
syllabus plan encounter 1 --db-path ./local.db
syllabus plan encounter 1 --route worked_explanation --db-path ./local.db
syllabus plan encounter 1 --route no_response_now --db-path ./local.db
```

`--module-id` selects a particular module; otherwise the first module is shown. The other optional routes are `short_written` and `spoken_under_two_minutes`. These commands only display stored material: they create no artifact, response, completion record or assessment. A prepared encounter remains `prepared_not_started` and `unassessed` until valid learner evidence exists. Understanding, enjoyment or a useful question can be enough; no public output is required.

## Inspect source support

Use each plan candidate's `document_id` and `chunk:N` locator:

```sh
syllabus corpus passage 1 0 --db-path ./local.db
syllabus corpus judge ./judgment.json --db-path ./local.db
syllabus corpus support 1 --claim 'Exact claim' --db-path ./local.db
syllabus corpus support --snapshot-id 1 --claim 'Exact claim' --db-path ./local.db
```

A judgment JSON requires `document_id`, `snapshot_id`, `sha256`, `chunk_index`, `claim`, exact `passage`, `reason`, `reviewer`, `reviewer_status`, `judgment_method`, `reviewed_at`, and `judgment`. Judgments are `supports`, `contradicts`, `uncertain`, or `does_not_support`. The passage must occur in the identified stored chunk. A human judgment requires both `reviewer_status: human_reviewed` and explicit `--human-reviewed` attestation. This is a local attribution contract, not authentication of the reviewer or machine verification of semantic truth. An assistant must never attest to nonexistent human review.

Human-reviewed support is scoped to the exact claim and passage. Use `--snapshot-id` to inspect judgments across distinct source documents, or a document ID for one source; choose exactly one scope. Contradictions are retained. Plans stay immutable and their candidates stay unverified; later judgments are retrieved separately. Source text is data, never instructions. File ingestion does not prove edition completeness or access to an audiobook.

## Adaptation configuration

`--purpose` accepts `understand`, `practice`, `evaluate`, or `enjoy`; `--medium` accepts `written_or_spoken`, `page`, `audio`, `practice`, or `mixed`.

Optional JSON profile fields: `access_conditions` (including `phone_only` and `source_available`) and `prior_task_evidence`. A task observation affects an `understand` or `evaluate` route only when it has a matching `module_id`, criterion `explain_with_counterexample`, a nonempty `response_locator`, and result `demonstrated` or `needs_work`. This criterion does not establish procedural skill or change a `practice` or `enjoy` route. It does not certify general competence; APS trusts supplied observations and does not verify the external response. Conflicting relevant observations remain visible even when prerequisites need inspection. Raw learner words and unrelated private context are not copied into encounter instructions. The full supplied profile still affects input identity.

When source access is unavailable, an independent inline example supports claim inspection. It does not establish instruction or transfer in the unavailable topic.

Audio suits exposition. Notation, diagrams, code, arguments and literary form require inspectable pages when relevant; procedures require practice. The original source argument remains separate from assistant explanation, analogy, critique and learner wording.

## Verification and compatibility

```sh
python -m pytest -q
ruff check .
mypy src --ignore-missing-imports
```

See [fingerprint and rollback contract](docs/implementation/learning-plan-integrity-v2.md). The independent legacy `generate` and database-backed generator are not the versioned `plan generate` persistence interface. Chamber hooks remain no-op extension points. External model personalization, finished multi-format artifacts and publication transports are roadmap work, not shipped behavior.

Historical design conversations under `docs/` retain their wording as source material. Their proposed schedules, compulsory Wings and personalized source rewrites are not current product contracts.
