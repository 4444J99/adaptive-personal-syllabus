# ADR 012 — Operating evidence: what keeps data, availability, cost, and recovery within bounds

- Status: accepted (bounded decision for #58, MTR-027)
- Decided: 2026-11-28, in PR `work/mentor/operating-readiness` (ranked-queue loop)
- Context: #58, implementation plan posted 2026-11-18 (comment 6989466112),
  re-verified live at main `ac5e6288` before building. Parent epic #6,
  control plan #21. Depends on #52 (merged via PR #91), whose outcome
  this decision consumes: the ledger checkpoint per append and the
  prefix-semantics verifier are the primitives the restore drill trusts.
  Depends on #54 (merged via PR #92), whose outcome this decision
  consumes: per-source freshness bounds and the refresh-run record are
  what the status check reads. Depends on #57 (merged via PR #100). #43
  (MTR-012, repo layout) is still planned and does not gate this
  delivery: the new files follow the existing layout.
- Evidence base: live tree at `ac5e6288` (post-#100 merge, 0 open PRs),
  verified through the GitHub API and a source-tarball read, plus a
  step-1 reproduction run against the work-copy CLI on synthetic data
  only (receipt: ranked-queue-build run files, `build-1128-0415-aps58-
  step1.md`). No `backup`/`restore` hits in `src/` or `tests/`; no
  `delete_*` in `storage.py`; `plan show --format json` carries the
  learner name and goals unredacted and `--format md` carries the name;
  `ledger verify` and `corpus stats` carry no profile content. Redaction
  of source paths (`redact_rel_path`) and secrets
  (`redact_secret_patterns`) already exists — what is missing is
  redaction of *learner* content. `export_all` generates sample paths
  from the seed; it is not a store export and a restore cannot consume
  it.

## Decision 1 — The local offer first, with a named owner

The operating owner is Anthony James Padavano (4444J99), the repo
owner-operator; the ranked-queue loop acts only via lease grants on #21
and never as the owner. Reasoning: the issue forbids a role placeholder
as the owner, and there is exactly one person who operates this system —
the person whose repo it is. A named owner is what makes the alert
drill and the degradation trigger answerable: when `ops status` fails,
one person is responsible for the next action, and the runbooks say
which action that is.

## Decision 2 — Reliability objective: integrity verifiable on every run

The store passes `PRAGMA integrity_check` (result exactly `ok`) and
`ledger verify` (chain valid, checkpoint matching) — checked by
`syllabus ops status`, which exits non-zero otherwise. Reasoning: the
store is one SQLite file and the ledger is the audit trail; an
integrity failure or a broken chain is the only failure mode the local
offer can observe directly, so the objective is stated in those terms
rather than in uptime language the evidence cannot support.

## Decision 3 — Freshness objective: per-source max age from #54

A source whose last good retrieval is older than its max age (default
168 hours, per source record) reads stale; `ops status` reports every
stale source and fails the run. Reasoning: #54 already built the
freshness machinery and the exclusion of stale sources from plans — this
decision consumes it as the freshness objective instead of inventing a
second one. A store with no sources has nothing stale; that is `ok`,
not a failure.

## Decision 4 — Backup freshness bound: 168 hours

A verified backup receipt must exist in the ledger no more than 168
hours old, or `ops status` fails. Reasoning: a store with no verified
backup has no recovery evidence, and the status command is where that
shows up instead of staying silent. The bound is one week: long enough
that a weekly operator cadence passes, short enough that a lost month
cannot hide. A restore does not itself satisfy the bound: the restored
store carries an `ops.restore` receipt but no backup receipt until the
operator backs the restored store up again — the backup file the
restore came from is a copy of an older store, not a backup of this
one. The bound is recorded in `docs/operating-budget.yaml`
and enforced by `ops status`; the test suite asserts the artifact and
the CLI's working copy agree.

## Decision 5 — Cost budget: $0 per month, marginal

The local offer costs $0/month marginal: it runs on the operator's own
machine, and no paid service is in the loop (CI is GitHub's free tier
for public repos). What changes it is adding any hosted service or paid
API — at which point the budget decision re-opens with the new number
in the artifact, not as a comment in a PR. Reasoning: "within bounds"
needs a bound that can be read back, and $0 with a named tripwire is
checkable; an unstated "cheap" is not.

## Decision 6 — Degradation trigger: any status check failing

When any `ops status` check fails (integrity, ledger, backup freshness,
source freshness), new ingestion and generation pause until the run is
green again; rollback is `syllabus ops restore` from the last verified
backup. Reasoning: the local offer has no traffic to shed and no
replicas to fail over to — the only honest degradation is to stop
writing new state until the evidence is green again, and the only
rollback is the restore drill the operator has already rehearsed.

## Decision 7 — Alert channel: local-only, no push channel

There is no push alert channel. The alert is `syllabus ops status`
exiting non-zero plus a ledger receipt, drilled per
`runbooks/alert.md`. An email or webhook channel is rejected for the
local offer: no service exists to deliver it and no secret exists to
hold it, and a webhook URL in the repo would be a credential-shaped
value with nowhere safe to live. Counterexample that would reopen it:
a named hosted alert service with its own objectives, owner, and
budget — which is the hosted offer in Decision 8, not a local addition.

## Decision 8 — Hosted offer: deferred, with a named reopen condition

No hosted offer is decided now. The local offer is the whole offer
until a hosted store or alert service is named with its own objectives,
owner, and budget. Reasoning: no hosted offer is named, no service
exists to deliver alerts or hold backups, and the local store is the
entire system — a hosted decision today would be a paragraph, not a
delivery. The counterexample that reopens it is a concrete named
service, not a general wish for one.

## Decision 9 — No uptime promise

No uptime promise is made. Reasoning: the local offer runs on one
machine the project does not control, and no measurement exists that
could honestly support a percentage. The reliability objective
(Decision 2) is what is promised instead: the store's integrity is
verifiable on every run, and the verification either passes or the
operator is told it failed.

## Decision 10 — Backup is a SQLite backup-API snapshot, not a file copy

`ops backup` copies the store with the SQLite backup API and checksums
the result; the receipt (path, SHA-256, bytes, source head hash, source
event count) is appended to the live ledger. Reasoning: a raw file copy
taken while a writer holds the database can be torn, and a torn backup
is worse than no backup because it looks like evidence. The backup file
itself stays a faithful copy of the store at backup time, so it does not
contain its own receipt event — the receipt lives in the live ledger,
and the restore drill proves the file.

## Decision 11 — Restore validates, swaps atomically, re-verifies

`ops restore` refuses a backup that fails integrity or ledger
verification (checked on a temp copy, so the backup file is never
touched), swaps it in atomically (`os.replace`), re-verifies the
restored chain on the live path, and only then appends the `ops.restore`
receipt. Reasoning: a restore that cannot prove the backup is good
before the swap is a way to destroy a working store with a bad file;
the receipt must never launder a bad restore, so verification precedes
it in both places.

## Decision 12 — Deletion removes the record, keeps the receipt honest

`ops delete-profile` deletes the profile row and its dependent plans
(stored payloads first — `plan_payloads` has no cascade) and appends an
`ops.delete-profile` receipt carrying counts only, never the name,
goals, or context. Reasoning: a deletion receipt that re-persists the
personal data it deletes is not a receipt. The `profile.init` ledger
event stays: the ledger is append-only (#52), and the receipt explains
the deletion instead of rewriting history. The profile file (if one was
written by `profile init`) is the operator's to delete; the runbook
says so. Deletion covers the database record; it is not a claim about
backups that already contain the record — those age out when the
operator rotates them, and the runbook says so plainly.

## Decision 13 — Redaction covers the plan-doc surface, not the log

`plan show` and `plan generate` take `--redacted`, which replaces the
learner name with `[redacted]` and clears goals and context in the
output copy only; the stored plan is untouched. Reasoning: step 1
reproduced the leak on exactly this surface (json and md plan output),
while `ledger verify` and `corpus stats` carry no profile content and
need no change. Redacting the append-only log would break the #52
chain; the redaction target is output, not history. The `profile init`
echo is deliberately unchanged: it prints what the operator just typed,
once, at creation time — it is not a diagnostic surface.

## Decision 14 — What this PR does and does not do

This PR delivers the `ops` commands, the redaction flag, the runbooks,
the budget artifact, this decision, and the contract tests. It does not
create a hosted offer, an alert channel, or an uptime promise; it does
not touch the profile file; it does not rewrite ledger history; it does
not close #58 (Implements, not Fixes — the issue stays open, and close
is the owner's call after the drills are run against a real store).

## What was verified, what was not

- Verified: the step-1 reproduction (backup/restore/delete commands
  absent; plan json/md leak the name and goals; ledger verify and
  corpus stats leak nothing); the #52/#54/#57 dependency deliveries
  (merged PRs #91/#92/#100, verified in the live tree); the
  `plan_payloads` missing-cascade that forces the delete order; the
  clean-room drill run in `tests/test_operating_readiness.py` (backup
  checksum, restore rebuild + verify, corrupt-backup refusal, deletion
  counts + receipt, redacted output, status verdicts) — all on synthetic
  data.
- Not verified (out of scope for this PR): the drills against a real
  learner store — the operator runs them from `runbooks/` on their own
  machine, which is the point of the runbooks; whether a hosted offer
  would change the budget — no hosted offer is named, so there is
  nothing to verify.
