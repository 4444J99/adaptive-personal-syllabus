# Source admission (MTR-017, #48)

> **Status of this plan:** This is one take, not a solidified plan. It is my current version of what I think should work, based on the source verified at the head named in the plan, and it needs further investigation and further hardening before and during implementation. Each step includes my reasoning for why, so the plan can be checked rather than trusted; where live evidence disagrees with the plan, the evidence wins and the plan gets revised.

Implements #48 (MTR-017) at main `8ee1538f` (loop PR, branch
`work/mentor/source-admission`): admission is a recorded, attributed
decision answering "may this source be used" — never inferred from
retrieval. Until this build, admission was containment + file extension
only: any regular file under the ingest root with an allowed extension
was admitted, with no ownership / license / access / provenance fields,
no admission authority, and no persisted distinction between title
metadata, recovered bytes, extraction, and usable passages.

## The defect, verified at the head

Reproduced at `8ee1538f` (synthetic corpus: one text doc, one binary
PDF): no admission table exists, `corpus --help` offers no `admit` /
`revoke` command, the `documents` DDL carries exactly the eight
plan-named fields (no owner, license, access, provenance, admitted-by),
the planner has no admission gate (it ranks by lexical overlap only and
stamps every candidate `source_support_unverified` /
`document_completeness: "not_established"`), and `corpus passage` on
the metadata-only PDF errors with no kind reported.

## Decisions (recorded, plan step 2)

- **Admission keying: `(root_path, rel_path, sha256)` via #54's
  `source_records`, not the plan's `(document_id, sha256)`.** *Why:* a
  document id is snapshot-scoped — a re-ingest of identical bytes mints
  a new document row and would silently drop every admission. Keying by
  source identity + exact bytes keeps an admission across re-ingests of
  unchanged bytes and invalidates it on sha drift, which is the plan's
  own rule. The granting `document_id` is stored for traceability only.
- **Decision vs content kind are separate.** Decisions are `admitted` /
  `rejected` / `revoked` (plus implicit `unadmitted`); `content_kind`
  is a persisted fact (`passage` / `metadata_only` /
  `extraction_failed`). *Why:* the plan lists `metadata_only` as both
  a decision and a kind, which lets it read as admitted-for-metadata or
  as rejected — exactly the ambiguity #48 exists to remove. The planner
  requires decision `admitted` AND kind `passage`; an admitted
  `metadata_only` document is usable as metadata, never as passage
  support.
- **Refresh stays observation.** A refresh re-reads containment-admitted
  sources regardless of the admission decision. *Why:* admission gates
  *use* (planner candidates, passage, support), not observation —
  otherwise no evidence could ever be gathered about an unadmitted
  source. One exception: a source whose latest decision is `revoked`
  is recorded `revoked` by refresh without re-reading bytes, the same
  as an inventory-refused source today.
- **Metadata-only candidates.** At `8ee1538f` the planner's chunk-join
  already keeps chunkless documents out of candidates, so the plan's
  "metadata-only document can appear in a candidate list" does not
  literally reproduce. The fix enforces the exclusion explicitly by
  `content_kind` + admission, and the observable `metadata_only` change
  is in `corpus passage` reporting (kind reported, no passage text) and
  candidate stamps.
- **Extraction failure.** Ingest keeps its fail-fast contract
  (malformed JSON/YAML tests pin it), so CLI ingest never produces an
  `extraction_failed` document today. The kind is defined and
  classified by the same helper; ingest does not swallow per-file
  errors to manufacture one.
- **No ledger event for admit/revoke.** *Why:* the admission table
  itself is the attributed, dated record, mirroring `corpus judge`,
  which also records a decision without a ledger event. A refresh —
  an operator run — keeps its `corpus.refresh` event.
- **First source:** the local ingest root already used by `corpus
  ingest`. *Why:* it is the authorized, available source; a remote
  fetcher is explicitly out of this build.

## What the admission record is

`source_admissions`, one row per decision; the latest row for a
`(root_path, rel_path, sha256)` source wins. A later admit re-admits a
revoked source; a later revoke supersedes an admit. Admit rows carry
the mandatory fields — `owner`, `license`, `access` (`public` /
`restricted` / `private`), `provenance`, `admitted_by`,
`admission_basis`, `reviewer`, `reviewed_at` — plus `admitted_at`.
Revoke rows carry `revoked_by`, `revocation_reason`, `revoked_at`.
Admission binds to exact bytes: a sha mismatch at admit/revoke time is
an error, never a silent carry-over.

- **License-contradiction tripwire.** At admit time the document's
  decoded text is scanned for a small explicit set of license-claim
  markers. A restrictive embedded claim against a permissive declared
  license (or the reverse) refuses admission. *Why:* the operator
  corrects the declared record instead of overriding the tripwire; the
  marker set is a tripwire, not a license parser, and is kept small
  and explicit in `admission.py`.
- **Private access redacts everywhere.** A `private`-access decision
  redacts the source's rel_path from `corpus stats`, plan output
  (`source_admission` exclusions and `source_freshness`), and the
  refresh summary; `corpus passage` and `corpus support` refuse it
  outright (no paths, no contents). A revoked source likewise leaves
  the support path. *Why:* the access field is the output gate the
  plan's step 7 requires — admission may say "usable", but private
  means "never emitted".

## What the planner does

`Planner.generate` reads the admission map for the snapshot once and
applies two exclusion passes after the freshness pass: a candidate must
be decision `admitted`, kind `passage`, and not `private`-access.
Excluded documents are listed in the plan's top-level
`source_admission` block (added after the fingerprint, like
`source_freshness`, with a per-status summary) so a plan says which
sources it kept out and why. Each candidate carries
`admission_status: "admitted"`, `content_kind`, and a computed
`document_completeness: "complete"` — the hard-coded
`"not_established"` is gone from both the planner and
`storage.get_passage`. Admission never promotes a candidate to support:
`source_support` stays `source_support_unverified` until a human
judgment says otherwise (#50).

## Commands

- `corpus admit <record.json>` — record JSON mirrors `corpus judge`:
  `document_id`, exact `sha256`, `owner`, `license`, `access`,
  `provenance`, `admitted_by`, `admission_basis`, `reviewer`,
  `reviewed_at`.
- `corpus revoke <record.json>` — `document_id`, exact `sha256`,
  `revoked_by`, `revocation_reason` (`reviewed_at` optional).
- `corpus passage` on a `metadata_only` / `extraction_failed`
  document reports `content_kind` with `text: null` instead of
  erroring on a missing chunk; on a `private`-access document it
  refuses outright.

## Verification

Fresh venv, `pip install -e .` with the CI seed layout (sibling
`koinonia-db` clone at `3fe455fc`): 251 tests pass (234 existing + 17
new in `tests/test_source_admission.py`, covering the plan's step-6
fixtures — contradictory license, revoked exclusion, sha drift,
symlink / `.private/` refusal — plus the step-7 privacy redaction and
the admit/revoke CLI round-trip); ruff clean, mypy clean, CLI smoke
green, docs-audit drift gate matched, claim self-check + pr-check
green. CLI demo (`aps48-demo.py`): unadmitted corpus yields zero
candidates; after admitting one public and one private doc, the
candidate list is exactly the public doc, the private path appears
nowhere in plan or stats output, and `corpus passage` on the PDF
reports `metadata_only` with no text.
