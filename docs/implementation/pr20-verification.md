# PR 20 implementation receipt

Owner: `organvm/adaptive-personal-syllabus#20`; branch `learning/plan-integrity-v2-2026-09-08`.
Base inspected: `9bd17d5ed860924cfbb15e1c177f57c1befffc40`.
Predecessor head: `2a778385b97c3fb4ab348e67ad3a43a640b79edd`.

## Review dispositions

| Thread | Finding | Repair and test |
|---|---|---|
| PRRT_kwDORPHIHc6gP6Xq | Boilerplate ranking | Module-title query; irrelevant-only regression |
| PRRT_kwDORPHIHc6gP6Xy | Repeated full corpus read | One snapshot load/tokenization; multi-module call-count test |
| PRRT_kwDORPHIHc6gP6X3 | Lost persisted integrity records | Atomic complete payload; restart retrieval and rendering equality |
| PRRT_kwDORPHIHc6gP6X- | Non-scalar Wings | Validate types before membership; malformed CLI profiles |
| PRRT_kwDORPHIHc6gQGxb | Non-object policy | Explicit rejection; six malformed policy cases |
| PRRT_kwDORPHIHc6gQGxi | Repeatability assertion | Exact replay and mapping-order tests, plus existing generation replay |
| PRRT_kwDORPHIHc6gQGxo | Locator bounds/stability | Snapshot/document/chunk retrieval, digest and repeatability fixtures |

## Executed local verification

Python 3.12.13, macOS ARM64. Seed dependency: koinonia-db `276b0c1ab4fa1e46c11938d60c638ba380cbff68`.

- `python -m pytest -q`: 75 passed.
- `ruff check .`: passed across the repository. Existing import/style findings and two equivalent minimum-selection expressions were repaired without suppressing the gate.
- `mypy src --ignore-missing-imports`: passed, 16 source files.
- `git diff --check`: passed.
- Docs audit: executed; all files ingested, suggestions present, recommended milestone present.

An initial run had 42 passes and four failures because the documented adjacent seed checkout was absent. Installing that dependency fixed the environment; no failing assertion was removed.

## Hosted execution gate

The predecessor's six check runs ended before executing steps. Python matrix jobs had no runner name. GitHub annotations report a billing lock. Repository Actions are enabled with allowed_actions=all. This is not a remotely executed code-test failure. No unchanged job was rerun and no protection was weakened.

Merge remains gated on administrator restoration of hosted execution and a successful current-head workflow/review batch. After restoring the account's Actions eligibility, run the current-head workflow once, inspect required checks and material review threads, and merge only after the governed gates pass. Local results do not substitute for that gate. No deployment was performed.

## Privacy and limits

Only reusable code, synthetic tests and generic documentation are included. No populated profile, learner response, library export, private PDF or private database was added. Historical full v1 payloads were never stored; retrieval exposes their original database projection without inventing missing fields. Source judgments rely on declared reviewer attribution, not authenticated identity or automated entailment. Wings artifacts are working sheets, not finished professional publications.

## Continuation at the next reviewed content revision

The continuation inspected `eda71292d5428c9df36b3d472f968258bd3d3930` rather than rebuilding the predecessor repair. All five newly open inline threads have a code/test disposition:

| Thread | Finding | Repair and test |
|---|---|---|
| PRRT_kwDORPHIHc6gYq9k | Unassessed DB generator selected advanced-only readings | Preserve all difficulty options while retaining unassessed status; align API default and test both |
| PRRT_kwDORPHIHc6gYq9n / PRRT_kwDORPHIHc6gYwJt | Missing artifact parent caused traceback | Actionable filesystem error; no success receipt or output overwrite |
| PRRT_kwDORPHIHc6gYq9v | Prerequisites erased conflicting task observations | Preserve evidence-review route and prerequisite instructions together |
| PRRT_kwDORPHIHc6gYq9y | Unavailable source still requested on screen | Inline activity and appropriate page/mixed/audio instructions; independent example scope explicit |

Additional negative cases repaired decoded-text loss behind a binary alias, hidden cross-document contradictions and uncertainty, invalid review dates, unsupported document-completeness declarations, and invalid numeric source selectors. A separate read-only encounter command exposes explanation and no-response views without recording performance. Optional artifact sheets remain assistant-authored.

Executed on Python 3.12.13, Linux x86_64, with `koinonia-db` at `276b0c1ab4fa1e46c11938d60c638ba380cbff68`:

- `PYTHONPATH=src python -m pytest -q`: 130 passed.
- `PYTHONPATH=src python -m ruff check .`: passed.
- `PYTHONPATH=src python -m mypy src --ignore-missing-imports`: passed, 16 files.
- `git diff --check`: passed.

The initial integration run executed 127 passing and three failing new numeric-selector regressions; the boundary was repaired and all 130 passed. These are actual local failures and repairs, separate from hosted infrastructure. Independent inspection verified their closure.

A separate synthetic rollback proof loaded the actual historical Storage implementation from base `9bd17d5`, opened the same SQLite database with current code, generated/retrieved/rendered v2 through the CLI, reopened with historical code, wrote a historical projection, and restored current code. All three records and the exact v2 payload survived; nine CLI reads across JSON/text/Markdown passed. No personal database was used.

Fresh hosted inspection of `eda71292` found five jobs with `steps: []`, `runner_id: 0`, and empty runner names. Four failed before starting with the annotation: "The job was not started because your account is locked due to a billing issue." Python 3.11 was cancelled by matrix fail-fast. No job executed; CodeQL's workflow-level success does not turn its failed zero-step job into a pass. The billing owner must restore execution eligibility before current-head hosted checks can satisfy the merge gate. No protection or review bypass is authorized by local results.
