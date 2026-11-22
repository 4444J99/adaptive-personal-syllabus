# ADR 004 — Ingest privacy boundary: classification-aware admission and redacted audit output

- Status: accepted (bounded decision for #34, MTR-007)
- Decided: 2026-11-22, in PR `work/mentor/ingest-canary-boundary` (ranked-queue loop)
- Context: #34, implementation plan posted 2026-11-18 (comment 6970124947),
  re-verified live at main `0060a8e1` before building. Parent epic #23,
  control plan #21. Depends on #33 (MTR-006, merged as PR #82): the
  classification inventory and this ADR's admission rule consume it.
- Evidence base: live tree at `0060a8e1` (156 tracked paths),
  `src/adaptive_personal_syllabus/corpus.py` (368 lines),
  `src/adaptive_personal_syllabus/docs_audit.py` (795 lines),
  `docs/privacy-classification.yaml` (28 entries), ADR 003, the merged
  PR #71 symlink-containment fix and its 5 boundary tests.

## Decision

1. **Admission is classification-aware.** `discover_documents` loads
   `docs/privacy-classification.yaml` when the scanned tree carries one
   (repo root, or the inventory itself at a docs root) and refuses any file
   whose root-relative path matches a `private-never-in-git` entry — even
   when its name and extension are otherwise admissible. The name-based
   floor (`SKIP_DIRECTORIES`, `SUPPORTED_EXTENSIONS`) stays in place
   underneath; classification is an additional refusal, never a bypass.
   `review` stays admitted per ADR 003 (keep, not move); `public` stays
   admitted. Private wins on conflict: an untracked file can match a public
   pattern and a private one (e.g. `docs-audit-ci.md` matches `*.md` and
   `docs-audit-ci.*`); refusal is the fail-closed side. A malformed
   inventory fails closed with `ERR_PRIVACY_INVENTORY` rather than
   silently admitting private paths. The inventory is read through the
   admitted-bytes path, so a symlinked inventory is refused like any other
   symlink escape.
2. **Content alone does not classify.** A supported-format file carrying
   private content in an ordinary directory is still admitted: the #33
   inventory classifies paths, not content, and an ordinary `notes.md`
   matches the inventory's public `*.md` entry. No content policy exists
   in this repo, and inventing one (secret heuristics at discovery) would
   over-block public files on a rule the owner never set. The residual is
   pinned by `tests/test_ingest_canary.py::test_ordinary_directory_canary_is_admitted`
   so it stays visible; a content policy is an owner decision, not a
   follow-up for this PR.
3. **Audit output never echoes credential-like values.** The docs-audit
   report echoes admitted file text outside the admitted store (extracted
   suggestions and use cases land verbatim in the report JSON/MD). Extracted
   item text is now scrubbed of substrings matching the four patterns the
   repo's own secret scan checks for (`sk-…`, `ghp_…`, `AKIA…`, `sk-ant-…`,
   `.github/workflows/secret-scan.yml`) before it enters any report. The
   suggestion is kept; only the value becomes `[REDACTED]`. The admitted
   store keeps the full text — only the report is scrubbed. `data_export`
   cannot echo ingest content by construction (sample paths derive only
   from seed data and hardcoded profiles); `db_generator` reads only
   taxonomy/reading metadata from Postgres and takes no ingest input, so
   neither needs a code change — both are covered by the sweep test's
   reasoning and, for the export, by execution.

## Alternatives considered, with the counterexample that decides each

- (a) **Content-scan at discovery vs path-classification only.** Scanning
  file bytes for secret-like patterns inside the admission predicate was
  considered: it would close the ordinary-directory canary case. The
  counterexample is the repo's own policy surface — there is no content
  classification policy anywhere in the tree (the inventory is path-based,
  the secret scan is a CI grep over tracked files), so a discovery-time
  scanner would be inventing the policy it enforces, with false-positive
  over-blocking as the failure mode (a public doc quoting a token format
  would stop being ingestible). Path-classification only wins; the content
  residual is recorded, not hidden.
- (b) **Drop extracted text from reports vs redact values.** Dropping the
  suggestion text from the audit report was considered: it would end the
  echo entirely. The counterexample is the report's purpose — the report
  exists to surface suggestions, and the extraction is the feature. The
  planted secret-like canary proves the echo is real (pre-fix, the report
  carried the full value); redaction keeps the feature and removes the
  exposure. Redact wins.
- (c) **Redact at report-write vs at extraction.** Scrubbing in
  `write_report` was considered: it is the last step before files. The
  counterexample is that the report dict is also printed to stdout by the
  CLI and consumed by the milestone execution plan — both bypass
  `write_report`. Extraction is the single choke point every downstream
  render consumes, so scrubbing there covers the JSON, the markdown, the
  milestone plan, and stdout. Extraction wins.
- (d) **Refuse `review` paths too vs keep them admitted.** Refusing
  `review` at discovery was considered: those paths carry unresolved
  rights questions. The counterexample is ADR 003 decision (2) — review
  means keep, not move, pending the owner's rights decision — and the
  audit gate's `all_files_ingested` assertion, which requires the audit to
  see every docs file. Refusing review would silently drop those docs
  from the audit and decide a rights question the evidence cannot answer.
  Keep-admitted wins.

## Deviations from the plan, decided on live evidence

- The plan's step 1 expected the ordinary-directory canary test to flip
  to non-admission once step 2 landed. It does not flip: the delivered
  inventory classifies paths, and the ordinary `notes.md` is public by the
  inventory's own `*.md` entry. What flips is the private-path canary
  test (a supported file at a `private-never-in-git` path — `*.egg-info/`,
  `.ruff_cache/`, `docs-audit-ci.*`, `.env*` — is admitted before step 2
  and refused after). The plan's acceptance criterion is satisfied by
  that test; the content canary is the documented residual above.
- The plan said the step-2 change consumes the inventory "in
  `discover_documents`/`allowed()`". It does — with one addition the plan
  did not name: the inventory is also found at a docs root
  (`root/privacy-classification.yaml`), because the audit gate scans
  `./docs` and the inventory lives at that root. Private patterns are
  depth-agnostic (`**/…`), so refusal works under either root.
- The plan named `db_generator.py` among the files to sweep. Read live,
  it takes no ingest input (Postgres taxonomy/readings metadata only) and
  cannot echo chunk text; it is not executed in the sweep, which covers
  the full local path ingest → audit → export. The sweep test asserts the
  canary is in the admitted store (database chunks) and in no produced
  artifact outside it.
- The plan's step 5 smoke test is re-run in this build: symlink refused,
  `.private` refused, classified-private file refused, public file
  admitted — all verified by the new tests, not by a manual run.

## Verification

- `tests/test_ingest_canary.py` (14 tests): private-path refusal (4 cases),
  public/review non-over-blocking, secret-pattern redaction (4 patterns),
  full sweep (canary in store, absent from report JSON/MD and export JSON).
- Full suite, `ruff check`, and `mypy src` green locally at the PR head;
  CI is the acceptance gate (test 3.11/3.12, classification guard, secret
  scan, docs-audit gate).
