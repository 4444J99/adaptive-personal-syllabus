# Runbook: alert

Owner: Anthony James Padavano (4444J99) — the repo owner-operator.
Decision: ADR 012 (Decisions 2, 3, 4, 6, 7). Issue: #58 (MTR-027).

## Purpose

There is no push alert channel for the local offer — no service exists
to deliver one and no secret exists to hold one. The alert is
`syllabus ops status` exiting non-zero plus a ledger receipt. This
runbook is the alert drill: how to check, what each failure means, and
what to do next.

## Command

```sh
syllabus ops status --db-path ~/.adaptive-syllabus/adaptive_syllabus.db
```

## Expected output

A JSON payload, exit code 0, `"ok": true`, every check `"ok"`:

- `store_integrity` — `PRAGMA integrity_check` returns `ok`.
- `ledger` — the hash chain verifies, checkpoint matching.
- `backup_fresh` — a backup receipt exists in the ledger no more than
  168 hours old.
- `source_freshness` — no source is older than its max age (default
  168h, #54).
- `budget` — always `ok`; it reports the $0/month budget, the owner,
  and the alert channel.

The output carries no profile content by construction — counts and
hashes only — so it is safe to paste into an incident note. For a
redacted view of a plan itself, use `plan show --redacted` or `plan
generate --redacted`.

## What "failed" looks like

- `store_integrity` fails — the SQLite file is damaged. Stop writing
  to it. Restore from the last verified backup
  (`runbooks/restore.md`); if no backup verifies, the store's contents
  are not recoverable from this machine and the loss is recorded in the
  ledger by the restore receipt (or its absence).
- `ledger` fails — the chain is tampered with, truncated, or
  malformed; the detail names the category. Do not append anything
  further to a tampered ledger: restore from the last verified backup.
- `backup_fresh` fails — no backup receipt, or the last one is older
  than 168 hours. Run `syllabus ops backup` (see
  `runbooks/backup.md`). Until a backup exists, the store has no
  recovery evidence, and that is what this failure is saying.
- `source_freshness` fails — one or more sources are stale. Run
  `syllabus corpus refresh` for the stale root; a source that stays
  stale already excludes itself from plans (#54).
- The command prints a failing payload for a store SQLite cannot open
  at all — that is the alert firing, not a reason to stay silent.

## While a check is failing

New ingestion and generation pause until the run is green again (ADR
012, Decision 6). Reading and verification may continue. Rollback is
`syllabus ops restore` from the last verified backup — never a hand
edit of the database file.

## Drill

On synthetic data only: build a scratch store, confirm `ops status`
fails with no backup, back it up, confirm it passes, corrupt a scratch
copy and confirm it fails. The test suite runs this drill on every CI
run (`tests/test_operating_readiness.py`). The operator's drill on a
real store is the same commands with the real paths.
