# Evidence-status contract

Parent statement: [docs-audit-truth.md](docs-audit-truth.md) — the audit
discovers intentions; it does not verify delivery. This contract is the
operational form of that statement: the exact record that moves an item
between statuses, the checks the generator runs on that record, and the
gate that keeps the committed report honest. It was written for
[#38](https://github.com/4444J99/adaptive-personal-syllabus/issues/38)
(MTR-039) and landed with that issue's build.

## Vocabulary

An item carries two independent fields. `status` is `planned` or
`implemented`. `verification_status` is `unverified` or `verified`, and it
is never null in emitted output. The two fields move together and only in
one direction through this contract: an item is `implemented` exactly when
its `verification_status` is `verified`, and `verified` exactly when a
valid verification record names it. A claim, a keyword match, a generated
report echo, or a status-yaml entry never changes either field on its own.

The legacy `planned` value means pending verification or disposition, not
proof that the implementation is absent. `implemented_count` counts
verified items only. Milestone `completion_pct` stays null because progress
cannot honestly be inferred from this audit (see the parent contract).

## What counts as evidence

A status moves from `planned` to `implemented` only on a verification
record in `implementation/milestones/*.verified.yaml`. One format exists;
there is no `evidence:` block inside a status yaml, and the generator
supports no second format. A record names the item ID, the exact merge
commit on the target branch whose green checks are the evidence, the
delivering pull request number, and the check runs by name and run ID,
each concluded `success`. The record's milestone supplies the item's
`implementation_tags` (a single `milestone.<name>` tag); keyword matches
stay in `implementation_claims` only, so the old keyword promotion path
stays closed.

The generator checks every record before it trusts one. The checkable
part runs offline: all required fields present, the head a full 40-hex
SHA, the pull request an integer, at least one check, every check naming
its run and concluded `success`. The live part runs against the checkout:
the record head must be an ancestor of the audited head, which is the
enclosing checkout's HEAD unless `--audited-head` names another head. A
merge commit on the target branch is an ancestor of the audited head;
an unmerged pull request has no such commit, and a fabricated head is not
an ancestor. The named check runs themselves are verified by the reviewer
at claim time — the record is a receipt, and the merge-evidence contract
(docs/merge-evidence.md, ADR 007) is the live verifier for merges. The
two contracts cover different evidence and neither substitutes for the
other.

## Rejection rules

Unknown IDs and malformed records fail the audit outright
(`DocsAuditError`): a status yaml or a verification file naming an item
the audit cannot see, a record missing fields, a head that is not a full
SHA, a non-integer pull request, an empty check list, or a cited check
concluded anything but `success`. Two records claiming the same item also
fail the audit — evidence must be unambiguous.

A well-formed record whose head fails the ancestry check is rejected with
a reason and listed in the report's `rejected_verifications`, not silently
dropped and not silently promoted: `stale-head` when git proves the head
is not an ancestor of the audited head, `unverifiable-head` when the head
does not exist in this checkout or the ancestry check itself cannot run,
`no-audited-head` when no audited head could be determined at all. The
item stays `planned` with `verification_status` `unverified`.

A `.verified.yaml` file is never ingested as a discovery source, wherever
it sits. The reconciliation file
(`docs/implementation/docs-audit-reconciliation.json`) is likewise
inventory, never discovery: it carries `artifact_kind`
`generated-docs-audit-reconciliation`, which the generator excludes from
extraction. The contract file itself is ordinary documentation; it is
guarded by a regression test asserting it adds no items, so a future edit
that introduces extractable wording fails locally before it reaches CI.

## The drift gate

The committed report (`docs/implementation/docs-audit-report.json`) must
be reproducible from the tree by the in-tree generator. CI regenerates
the report on every run and compares it against the committed file,
ignoring only run-varying metadata (`generated_at`, `root_path`, and the
snapshot block, which records the throwaway ingest database), the manifest
entries for the audit's own two outputs (the report and the roadmap
markdown — their hashes are inherently one regeneration behind on the CI
path, where the outputs land outside the tree, versus the commit path,
where the CLI excludes its write targets from discovery), and the
manifest-length-derived ingest counts (redundant with the manifest list
itself). Any other difference — a new item, a changed status, a changed
file manifest, a new rejection — fails the job until the committed report
is regenerated. The generator records `root_path` as invoked (`docs`),
never as an absolute machine path, so a committed report does not leak
checkout locations and reproduces across machines. The roadmap markdown
(`docs/implementation/docs-audit-roadmap.md`) is the rendered form of the
same report and is regenerated with it.

## Reconciliation at this contract's landing

At main `6b2b4b90` the committed report held 386 items with 58 labelled
`implemented`, all with null verification status, generated 2026-02-18
under schema 1.0. The current generator yields 388 items, 0 implemented:
the 58 split into 29 backed only by the status yaml and 29 promoted only
by keyword rules, and neither half carries a verification record. The
status yaml arrived by direct commit `47d1198d` (2026-02-18) with no
delivering pull request, and the only pull request naming the milestone
is #72, which stopped certifying claims as delivery — so no honest record
could be constructed for any of the 58. All 58 demote to `planned`, 29
with reason `unverified-claim` and 29 with reason `keyword-only`, in
`docs/implementation/docs-audit-reconciliation.json`. The 2-item growth
from 386 to 388 is genuine new content (ADR 003, mentor-roadmap-state.md),
not generated-output echoes: the issue body's "fresh 390" with 4 echoes
does not reproduce at this head, because generated outputs are excluded
from extraction by marker and path.
