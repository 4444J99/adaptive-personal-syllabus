# ADR 013 — First domain slice: one world-studies source, one module, one encounter

- Status: accepted (bounded decision for #59, MTR-028)
- Decided: 2026-11-28, in PR `work/mentor/first-domain-slice` (ranked-queue loop)
- Context: #59, implementation plan posted 2026-11-18 (comment 6989721889),
  re-verified live at main `680b6e59` before building. Parent epic #28,
  control plan #21. Depends on #48 (merged via PR #93), whose outcome
  this decision consumes: the admission record is what makes the excerpt
  usable by the planner, and the license-contradiction tripwire is what
  the source decision is checked against. Depends on #50 (merged via
  PR #95), whose outcome this decision consumes: the span-grounded
  judgment is what records the passage inspection, and the reviewer
  allowlist is what bounds who may attest human review. Depends on #54
  (merged via PR #92), whose outcome this decision consumes: the refresh
  observation is what the slice's source freshness reads. Depends on #56
  (merged via PR #99). #47 (MTR-016, rubric evolution) is still planned
  and does not gate this delivery: the slice declares its own evaluation
  (Decision 5) instead of depending on rubric machinery. #49 (MTR-019,
  catalog reconciliation) is still planned and does not gate this
  delivery: the slice admits one source directly under #48's rules
  instead of through catalog machinery.
- Evidence base: live tree at `680b6e59` (post-#101 merge, 0 open PRs),
  verified through the GitHub API and a source-tarball read, plus a
  step-1 reproduction run against the work-copy CLI on synthetic data
  only (receipt: ranked-queue-build run files,
  `build-1128-0615-aps59-step1.md`). `plan generate` for a synthetic
  world-studies profile returns 0 modules; grep for `first-domain` /
  `MTR-028` / `world-studies` across `src/`, `docs/`, `data/`,
  `BRANCHES.md`, `CHANGELOG.md` returns zero hits. No world-studies
  module, no domain registry, no slice concept exists anywhere in code
  or docs.

## Decision 1 — The source: Herodotus, Histories Book 2, the Nile-flood discussion (Rawlinson)

The slice's one source is the Nile-flood discussion, Book 2 chapters
19–25, in George Rawlinson's translation, as published on Wikisource
(page `The History of Herodotus (Rawlinson)/Book 2`, revision 7044570,
2017-10-13T09:17:51Z, retrieved 2026-11-28), committed verbatim as
`data/slices/herodotus-nile-flood.md` (sha256
`1938c046b596cc31a19487f3d51349d38ae82ab05cdee8dd6dda5aa80d1a4a5f`).
Reasoning: the issue forbids preselecting a source, and no eligible
world-studies source exists in the repo — so the decision comes first,
in the open. The passage is a claim with reasons and rejected
alternatives (the Etesian-winds, Ocean, and snow theories, each answered
with an observed counterexample), which is the exact shape the slice's
criterion `explain_with_counterexample` needs: a learner can state the
claim, its reason, and one case where that reason is insufficient. The
work is public domain (author died c. 425 BCE; translator died 1902),
the edition is pinned by revision id, and the fetch was verified from
this environment this run. The excerpt is the discussion only, not the
whole book: one slice proves the path, not the domain.

## Decision 2 — Rejected: CIA World Factbook Egypt entry

Public domain and stable (annual editions), attributable and
recoverable — but a fact list, not an argument. Reasoning: it gives
facts, not a reasoned claim to explain with a counterexample, so it
cannot carry the slice's criterion. Counterexample that would reopen
it: a Factbook passage that states a claim with a reason and a case
where the reason fails — none exists in an entry shaped as a fact table.

## Decision 3 — Rejected: OpenStax World History (CC BY)

Openly licensed and versioned — but the web-book edition drifts between
printings, extracting a stable short passage needs a large-book
download, and the passage would be expository rather than
argumentative. Reasoning: the slice needs a pinned edition whose wording
does not move under the judgment's span, and an argument with a
counterexample; OpenStax gives neither as directly as the Herodotus
passage. Counterexample that would reopen it: a pinned release PDF with
a stable, argument-shaped passage.

## Decision 4 — Rejected as the committed edition: Gutenberg #2707 (Macaulay)

The first choice on edition stability — but unrecoverable from the build
environment on 2026-11-28: gutenberg.org returned 503 Service
Unavailable with `retry-after: 21600` on every path tried (plain text,
cache/epub, alternate mirror host). Reasoning: a source that cannot be
fetched cannot be verified, and the slice records its source version so
a re-pin is a defined operation rather than a silent substitution. The
Macaulay edition remains the named re-pin candidate: a successful fetch
re-opens this decision, and the excerpt is then re-pinned to the
Macaulay text with this ADR updated. Overturning counterexample for the
chosen source: a showing that the Rawlinson text on Wikisource is not
the Rawlinson translation, or that the excerpt's wording differs from a
stable printed edition in a way that changes the argument.

## Decision 5 — The slice shape: one registry entry, one module, one prerequisite, one criterion

The slice is a registry entry in `data/slices/world-studies-first-slice.json`:
domain `world-studies`, one module
(`world-studies-nile-flood-beg`, "Why the Nile Floods in Summer",
beginner, 2.0 hours, readings [the source title], one prerequisite:
"Locate the admitted Nile-flood passage in the snapshot (its chunk
locator) before the encounter"), one criterion
(`explain_with_counterexample`), and the source record (title, author,
translator, edition, URL, revision, retrieval date, license, file,
sha256). Reasoning: modules come from the koinonia-db seed via
`SyllabusGenerator`, which carries the eight-organ taxonomy — world
studies is not an organ, so the slice cannot be a seed node. The
registry keeps the slice definition next to its source file and its
evaluation rule, in one reviewable place, instead of hiding a domain
inside the generator. The prerequisite is the source-location
precondition, not a module dependency: the slice has one module by
design, so there is no second module to depend on, and the encounter
renders the prerequisite as the instruction to inspect before
proceeding. The criterion is not a module field — it lives in the
encounter's prior-task-evidence matching — so the registry records it
under `evaluation` and the tests assert the encounter routes on it.

## Decision 6 — The planner merge: slice modules join generate only for their domain

`Planner.generate` merges slice modules whose domain matches a profile
organ (mapped the same way the generator maps organ codes), before
module rows are built, so a slice module flows through the same source
selection, adaptation, fingerprint, and persistence as an organ module.
Reasoning: the seed-dir-only alternative would leave the slice
unreachable from the default CLI path — a module that only exists in
tests is not a delivered slice. A profile that never names the domain
never gets the module (unknown domains yield none), and the registry
loader fails loudly on a malformed file rather than silently dropping a
slice (a half-defined slice that vanished from a plan would read as "no
slice exists", the exact failure step 1 reproduces). The CLI gains
`--slice-dir` (mirroring `--seed-dir`) so the stranger flow can point
at the sdist tree's `data/slices/`; the sdist ships it via a MANIFEST.in
graft, mirroring the seed fixture.

## Decision 7 — The route correction: prerequisite_check, not first_encounter

The plan expects the slice's first encounter to route `first_encounter`;
with one prerequisite the machinery routes `prerequisite_check`
(`encounter.py`: non-empty prerequisites → `prerequisite_check` unless
`evidence_review`). Reasoning: the plan's expectation is wrong at this
head — the rule predates the plan — and the evidence wins over the
plan. The slice records the observed route; it does not remove the
prerequisite to chase the expected route, because the acceptance checks
require one prerequisite.

## Decision 8 — The support boundary: assistant review is recorded, human review flips

The slice records one assistant-reviewed judgment (method:
span-grounded inspection, reviewer `synthetic-reviewer`) on the
Etesian paragraph, pinning the exact span. The module's
`claim_support_status` stays `source_support_unverified`. Reasoning:
only a human-reviewed `supports` flips the status
(`support.py`), and the loop cannot attest human review — only `4jp` /
`4444J99` are human identities in `docs/reviewers.yaml`. Recording an
assistant judgment as if it were support would be the dishonest-green
failure this repo's rules exist to prevent. The flip condition is named
in the slice registry's evaluation rule, not satisfied: a second slice
is permitted only after (a) a human-reviewed `supports` judgment flips
this slice's passage to `human_reviewed_support`, and (b) one authentic
learner response with a `response_locator` is recorded against the slice
module. A `needs_work` result, a contradictory judgment, or a
superseded judgment requires revision of the module before any
expansion.

## Decision 9 — Known limitation: lexical ranking demotes the theories chunk

The planner's lexical ranking surfaces the problem chunk first; the
three-theories chunk ranks below the top 3 (it carries neither "summer"
nor "why" among the module title's tokens), so it is not among the
module's displayed candidates. Reasoning for recording rather than
fixing: judgments attach by document, not by chunk, so the Etesian
passage is still judgeable for this module and the acceptance holds —
the ranking only affects which chunks are displayed, not what can be
judged. Changing the ranking to favor the theories chunk would be a
second intention in this PR (one intention per PR); the limitation is
recorded here and in the test, and a ranking change is a named
follow-up if a later slice needs a different chunk surfaced.

## What this decision does NOT do

It does not build #47 (rubric evolution), #49 (catalog reconciliation),
or #54's remote fetch (no live remote fetch exists in the CLI; refresh
re-reads the committed file). It does not add a domain registry beyond
the one-slice registry file. It does not claim human-reviewed support.
It does not close #59.
