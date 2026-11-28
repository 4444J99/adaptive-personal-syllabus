# ADR 009 — Output authorship and publication: a bounded publish step gated by the ledger

- Status: accepted (bounded decision for #55, MTR-023)
- Decided: 2026-11-27, in PR `work/mentor/output-authorship` (ranked-queue loop)
- Context: #55, implementation plan posted 2026-11-18 (comment 6989134315),
  re-verified live at main `b888f586` before building. Parent epic #27,
  control plan #21, Wave 3. Depends on #51 (merged via PR #97 at this
  head), #52 (merged), #42 (ADR 005, merged via PR #84) — the dependency
  gate the plan recorded as "all planned" is fully satisfied, so the
  delivery half of #55 is unblocked.
- Evidence base: live tree at `b888f586` (post-#97 merge, 0 open PRs),
  verified through the GitHub API, a source-tarball read, and a step-1
  reproduction via the installed CLI (synthetic corpus/profile/plan).
  `plan artifact` (`core.py:649`) writes an assistant-authored working
  sheet, local only, with an atomic exclusive write and a
  `artifact.generate` receipt carrying `publication_authorized: False`.
  `plan authorize-publication` (`core.py:700`) records a separate
  authorization for exact bytes (sha256) and a named destination and
  performs no publication. No revoke/deny path exists: `syllabus plan
  revoke-publication` answers "No such command" (the existing `corpus
  revoke` is source-admission revocation, a different domain), and
  `plan artifact` has no `--learner-words-file` option. The artifact
  still renders the blanket "Assistant-authored scaffold; not
  learner-authored work.", "Learner words: [not supplied]", and the
  hardcoded "Source support: unverified" (`core.py:664`, `674-675`).
  Plan modules carry a real per-module `source_selection.
  claim_support_status` (verified in step-1: `source_support_unverified`
  with no judgments on the synthetic plan), so the hardcoded source line
  can be replaced with the live value. The leak guard's behavior holds —
  step-1 found neither the `PRIVATE_CONTEXT_NOT_FOR_OUTPUT` sentinel,
  the profile name, any goal, nor the context object in artifact bytes —
  and the sentinel part is already proven by test
  (`tests/test_output_policy_integrity.py:122`, `:204`); only the
  profile-name / goals / context-object assertions are still missing.

## Decision 1 — A `plan publish` step inside the repo (alternative ii)

Learning becomes art or professional work through one bounded step:
`syllabus plan publish <artifact> --destination <dir>`, which copies the
exact authorized bytes to a named destination directory. Reasoning: the
issue asks *how* learning becomes art or professional work, not whether
it does, and authorize-only leaves that question with no in-repo path —
the authorization record would stay advisory, and nothing could ever
verify that a published artifact matches the authorized bytes. A publish
step makes the authorization enforceable instead of advisory, and it is
the smallest change that answers the question: the step does nothing but
re-verify the ledger and copy.

## Decision 2 — Who publishes, and where the authorization check lives

The learner (the CLI operator) publishes; the repo never publishes on
its own, and no command publishes as a side effect of generating or
authorizing. The authorization check lives in `plan publish` itself: it
reads the ledger and takes the latest event for the exact
(`artifact_sha256`, `destination`) pair among
`artifact.publication_authorization` and
`artifact.publication_revocation`. Publication proceeds only when that
latest event is an authorization with `publication_authorized` true.
Reasoning: the check must sit at the point of publication, not in the
artifact or the authorization record, because only the publish step can
bind the bytes on disk to the destination at the moment of copying — an
authorization recorded earlier cannot know what the bytes will be when
someone later asks to publish them.

## Decision 3 — What a revoked authorization blocks

A revoked (or denied) authorization blocks the publish copy, with a
distinct refusal and no receipt — nothing is written, nothing is
published, and no `artifact.publication` event is appended. The refusal
names the reason the lookup found (no authorization, revoked, or
denied). Reasoning: a revocation that merely warned would leave the
authorization advisory again; the block must be total, at the copy,
because the copy is the only irreversible act in this flow.

## Decision 4 — Revoke is one command for deny and revoke

`plan revoke-publication <artifact> --destination <d> --reason <r>`
appends an `artifact.publication_revocation` event carrying the artifact
sha256, the destination, the reason, `publication_authorized: False`,
and `publication_status: "not_published"`. It records the revocation
whether or not an authorization already exists: before any authorization
it is a denial, after one it is a revocation, and the latest event wins
in either case. Reasoning: the issue's acceptance asks for denied
authorization and revoked output tests, and both are the same lookup
rule — latest event decides — so one command and one event type cover
both, instead of two commands that could disagree about which one the
publish step consults.

## Decision 5 — Destination is part of the authorization identity

`--destination` names an existing directory, and the authorization binds
to the exact destination string: authorize and publish must name it
identically, or the lookup finds no authorization and refuses. The copy
lands as `<destination>/<artifact filename>`, written exclusively — it
never overwrites an existing path — and the `artifact.publication`
receipt records the artifact sha256, the destination, the published
path, and `publication_status: "published"`. Reasoning: a destination
that is only a label cannot be enforced; binding the exact string keeps
"authorized for this destination" checkable, and the exclusive write
keeps publication from silently replacing bytes someone else put there.
Publication never mutates the authorized bytes: the copy is byte-for-byte
the file that was authorized, and a modified file has a different sha256
and therefore no authorization.

## Decision 6 — Per-line attribution in artifact rendering

The blanket header and the hardcoded source line are replaced with
per-section attribution. The header states the three attributions
(assistant scaffold; source support stated per module; learner-authored
text appears only in the learner section, when supplied). Each module
renders its real `source_selection.claim_support_status` — the live
value, never a hardcoded one — plus the `missing_support` note when no
human-reviewed support is attached. Assistance stays labeled by the
existing "Assistant explanation:" lines. Learner-authored text is
attached with `plan artifact --learner-words-file <path>`: the file's
bytes are copied verbatim into a learner section marked `Authorship:
learner`, and the `artifact.generate` receipt records
`learner_words_sha256`; with no file supplied the receipt records
`learner_words_sha256: null` and no learner section is rendered.
Reasoning: the issue's second question is how source attribution,
assistance, user-authored text, and publish authorization are recorded
separately, and a blanket header cannot answer it — only per-section
labels can. The learner supplies the file, so the words stay under
their control: the repo copies them exactly, never rewrites them, and
the receipt proves which bytes were attached.

## Rejected alternatives, with counterexamples

- **(i) Authorize-only.** The authorization stays a ledger record and
  publication happens outside the repo by hand. Counterexample: a
  learner authorizes exact bytes for a destination, then publishes a
  different file by hand — nothing in the repo can detect it, because
  the repo has no publish step to check against. The question "how
  does learning become art or professional work" would still have no
  answer in the code, and the issue's "a plan, draft PR, checklist ...
  is not delivery" rule would leave the delivery half unbuilt.
- **(iii) No publication ever.** Artifacts stay local working sheets
  and the publish question is closed as out of scope. Counterexample:
  the issue's premise is that learning *should* be able to become art
  or professional work under authorship and consent — closing the
  question contradicts the premise instead of resolving it, and the
  eight Wings exist as an output vocabulary for exactly that purpose.
  The artifact command's own "never publish" docstring describes the
  working sheet, not the product; this decision does not change it.

## Remaining uncertainty

- The destination is a local directory in this decision. A remote
  channel (a hosted page, a feed, a marketplace) would need its own
  authorization shape — destination as a path cannot name one — and is
  explicitly out of scope until an issue asks for it.
- The learner-words attachment takes one file for the whole artifact.
  Per-module learner words (for example, drawn from the
  `encounter.receipt` verbatim `learner_words` #51 records) would
  attach words to the module they answer; that is a later issue if
  anyone wants it.
- Revocation is recorded in the ledger, which is append-only: a
  revocation cannot be un-revoked except by a later authorization
  event, which the lookup treats as the new latest event. Whether a
  re-authorization after a revocation should require a fresh reason is
  undecided and untested.
