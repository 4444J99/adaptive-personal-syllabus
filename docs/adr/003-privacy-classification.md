# ADR 003 — Privacy classification: which assets may be public, must remain private, or must never enter git

- Status: accepted (bounded decision for #33, MTR-006)
- Decided: 2026-11-21, in PR `work/mentor/privacy-classification` (ranked-queue loop)
- Context: #33, implementation plan posted 2026-11-18 (comment 6969870941),
  re-verified live at main `f8325de8` before building. Parent epic #23,
  control plan #21. Depends on nothing; gates #34 and #42.
- Evidence base: live tree at `f8325de8` (158 tracked paths), `SECURITY.md`,
  `BRANCHES.md`, `storage.py`, `docs_audit.py`, the three incident commits
  `db66c96` / `0fa627b` / `3ba1c28`.

## Decision

1. **The runtime database is untracked now.** The tracked audit database is
   removed from tracking; the live runtime database lives in the owner's
   home runtime directory (the `DEFAULT_DATA_DIR` named by `storage.py`);
   the audit database is reproducible on demand with
   `syllabus docs audit --db-path <private path>`.
2. **Transcripts and personal guides stay `review`.** The AI-chat exports,
   the personal writing guides, and their duplicates under
   `docs/source-materials/theory/` are kept, not moved, not relicensed. The
   rights decision is the owner's.
3. **Home paths are redacted to repo-relative or portable form.** Provenance
   paths become repo-relative (provenance by hash survives); the stale
   audit-run root paths become repo-relative; the knowledge-graph database
   path in `docs/seed.yaml` becomes home-relative (`~` form). No absolute
   home-directory path remains in any tracked file.
4. **Build outputs are untracked and ignored.** The `egg-info` tree is
   removed from tracking; `.gitignore` covers every forbidden class.
   Tracked `__pycache__`/`*.pyc` files were already dropped by merged #80.

## Alternatives considered, with the counterexample that decides each

- (a) **Untrack now vs keep a scrubbed fixture.** A scrubbed fixture was
  considered: the database holds real document text derived from already
  tracked docs, so a scrubbed copy would add nothing the tree does not
  already contain, while still leaving a runtime artifact in public git.
  The observed fact that no code references the database filename — it is
  an orphan artifact, not a live store — decides for untracking now. The
  live store is the runtime default directory, and the audit database is
  reproducible, so nothing load-bearing is lost.
- (b) **Keep vs redact vs move, per transcript class.** Moving the
  transcripts out of public git was considered and rejected for this PR:
  no item here is established as third-party material, and the #76
  precedent (third-party material is removed, not relicensed) applies only
  to established third-party material. Redacting the transcripts would
  destroy their content without a rights finding. Keeping them as `review`
  is the only treatment that does not decide a rights question the evidence
  cannot yet answer.
- (c) **Redact vs accept the home paths.** Accepting was considered: the
  paths name only the owner's workspace, and the files are historical
  artifacts. The counterexample is the corpus #143 parallel — the same
  class of exposure, already treated as a defect there — and the fact that
  provenance by hash survives redaction, so redaction costs nothing and
  removes the exposure. Redact wins.
- (d) **Untrack vs keep the build outputs.** Keeping was considered: the
  `egg-info` files are small and inert. They are regenerable on every
  install, they are not load-bearing for any test (tests use temporary
  fixtures), and the policy forbids build outputs in public git. Untrack
  wins.

## Deviations from the plan, decided on live evidence

- The plan said the tracked `__pycache__`/`*.pyc` files were still tracked.
  They are not: merged #80 dropped them (22 files removed between the
  plan's head `019dfc70` and this head). Only the `egg-info` tree remained
  of that class, and it is removed here.
- The plan said "the database is regenerable — `docs_audit.py` rebuilds
  it". That is imprecise: no code path regenerates that exact filename —
  nothing in the tracked tree references it. What is true is that the audit
  database is reproducible on demand by re-running the audit with an
  explicit `--db-path`, and the runtime database default is the home
  runtime directory. The decision (untrack now) stands on the corrected
  evidence.
- The plan named one file carrying absolute home paths
  (`PROVENANCE.yaml`, 39 paths). A full-tree scan found three more files
  with one path each: the stale audit report and roadmap (audit-run root)
  and `docs/seed.yaml` (knowledge-graph database path). All four are
  redacted in this PR; the classification test now scans the whole tree so
  a fifth cannot arrive silently.
- The plan's history review (step 5) is scoped, not completed, in public:
  the three incidents are confirmed at metadata level, but whether
  anything from them persists in history and whether rotation is owed is a
  private-channel determination per `SECURITY.md`, and it is not recorded
  here. No history was rewritten.

## Observed result (to be filled by CI at the PR head)

- Classification test green; `git ls-files` shows no `*.db`,
  `__pycache__`, `*.pyc`, or `egg-info` paths; `.gitignore` covers every
  forbidden class; the guard workflow runs on PR heads.
- `PROVENANCE.yaml` carries no absolute home path; the private inventory
  exists outside public git with a public receipt (counts and classes only,
  in `docs/privacy-classification.md`).

## Next step

- #34: consume this inventory in `discover_documents`/`allowed()` so a
  file classified private is refused at discovery even when its name and
  extension are otherwise admissible.
- #42: write the public/private component contract against this inventory.

## Remaining uncertainty

- The rights status of model outputs (Grok/Claude/GPT/Gemini) and of the
  personal guides is still undecided; both stay `review` until the owner
  decides.
- Whether anything from the three history incidents persists in history,
  and whether rotation or notification is owed, is a private-channel item.
- Main is still unprotected (verified at the claim head), so the guard is
  CI-advisory only; protection and rulesets are the owner's action.
- The `docs/seed.yaml` database path is consumed by external metasystem
  tooling, not by this repo's code; the portable home-relative form is the
  standard spelling, but the consumer was not verified here.
