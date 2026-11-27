# Source support — what proves a passage supports an instruction

Status: implementation of adaptive-personal-syllabus #50 (MTR-020), main
`783ab21b`. This document records the entailment / authentication /
invalidation contract the code enforces. It is the place the source-support
contract is documented (plan step 7).

## The rule in one paragraph

Lexical relevance is never support. A retrieved passage becomes evidence
for an instruction only through a validated, attributed judgment: a known
reviewer, using a registered method, pinning the exact grounding span in
the inspected chunk, at a named snapshot. The plan a learner sees carries
only validated judgments; anything else reads as unverified, uncertain,
contradictory, or superseded — never as proof of truth.

## What a judgment is

A judgment (`src/adaptive_personal_syllabus/support.py`,
`validate_judgment`) names a claim, the exact quoted passage, a reason,
a reviewer, a method, and a review date, bound to one document, chunk,
and snapshot by hash. It is recorded by `storage.record_source_judgment`
(and the `syllabus corpus judge` CLI) and stored as a payload in the
`source_judgments` table.

## Entailment: the span is the checkable basis

- The only passage check that is mechanical is occurrence: the quoted
  passage must occur verbatim in the inspected chunk. Occurrence proves
  the quote exists, not that the passage entails the claim.
- A `supports` judgment must therefore also pin a grounding span
  (`span_start`/`span_end`): a non-empty span inside the chunk whose text
  is exactly the quoted passage. A judgment with no verifiable span
  cannot be `supports` and is rejected at record time.
- No entailment or NLP service is selected by this contract. The span is
  the machine-checkable basis; what the span means is the reviewer's
  attested judgment, recorded with the method that produced it.
- `judgment_method` must name a method in the registry in `support.py`
  (`exact passage inspection`, `span-grounded inspection`). Free text
  cannot name a method, so it is rejected.

## Authentication: the reviewer must resolve

- The reviewer must resolve to a known identity in `docs/reviewers.yaml`
  (the repo's own seed/config; no new service). An unknown reviewer is
  rejected, not recorded.
- The identity's kind must match the attested `reviewer_status`: only a
  human identity can attest `human_reviewed`; an assistant or synthetic
  identity attests `assistant_reviewed`. The stored record carries the
  resolved identity (`reviewer_id`/`reviewer_kind`), not just the
  supplied name.
- The CLI (`syllabus corpus judge`) additionally requires the explicit
  `--human-reviewed` flag for a `human_reviewed` record: human review is
  never inferred from retrieval.

## Invalidation: a superseded judgment is history, not evidence

- When a source is re-ingested into a new snapshot with changed content,
  the ingest marks the prior snapshot's judgments on that document
  `superseded` (`storage.supersede_stale_judgments`, called from
  `CorpusIngestor.ingest` in the same transaction). An unchanged
  re-ingest supersedes nothing: same bytes, same evidence.
- Supersession never deletes history. The stored row keeps every original
  field and gains `status: superseded` plus `superseded_by_snapshot_id`,
  `superseded_at`, and `superseded_reason`.
- `summarize_judgments` computes the status over live judgments only and
  lists superseded records alongside it (`superseded`,
  `superseded_count`), so a stale `supports` can never read as live
  support.
- `syllabus corpus support --revalidate` re-checks stored judgments
  against the latest snapshot and supersedes those whose passage no
  longer verifies — the pass that catches judgments recorded against an
  old snapshot after a newer one already exists, or recorded before
  invalidation shipped.

## How plans carry judgments

- `Planner.generate` attaches, per module, the validated judgments for
  the plan's snapshot whose document is among that module's selected
  candidates. Modules carry no claim strings, so the checkable filter is
  the module's selected sources.
- `claim_support_status` derives from the attached live judgments
  (worst case across claims: contradictory, then uncertain, then
  human_reviewed_support, then unverified). Superseded judgments are
  listed separately (`superseded_judgments`) and never count toward the
  live status. The `missing_support` message appears only when no
  validated judgment exists.
- Judgments enter the plan fingerprint: they are plan content, not
  time-varying observation like freshness, so a plan whose evidence
  changes is a different plan.
- Admission and revocation compose with this contract rather than
  replacing it: an unadmitted, private, or revoked source never reaches
  a plan candidate (#48), so its judgments cannot attach; a superseded
  judgment is history, a revoked source is exclusion — different states,
  both visible.
