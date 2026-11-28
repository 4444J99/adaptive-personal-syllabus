# Runbook: restore

Owner: Anthony James Padavano (4444J99) — the repo owner-operator.
Decision: ADR 012 (Decisions 6, 11). Issue: #58 (MTR-027).

## Purpose

Rebuild the live store from a verified backup after loss or corruption,
and prove the rebuilt store before the restore receipt is written.

## Command

```sh
syllabus ops restore --backup ~/backups/adaptive-syllabus-2026-11-28.db \
  --db-path ~/.adaptive-syllabus/adaptive_syllabus.db
```

## What happens, in order

1. The backup is verified on a temp copy: `PRAGMA integrity_check`
   must return `ok` and the ledger chain must verify. A backup that
   fails is refused and the live store is untouched.
2. The backup bytes replace the live store atomically (`os.replace`).
3. The restored chain is re-verified on the live path.
4. Only then is an `ops.restore` receipt appended to the restored
   ledger, recording the backup SHA-256, the previous live head hash,
   and the restored event count.

## Expected output

A JSON receipt, exit code 0:

```json
{
  "operation": "restore",
  "db_path": ".../adaptive_syllabus.db",
  "backup_path": ".../adaptive-syllabus-2026-11-28.db",
  "backup_sha256": "<64 hex chars>",
  "previous_head_hash": "<live head before the swap, or <unreadable>>",
  "restored_event_count": 42,
  "backup_event_count": 41
}
```

Afterwards, re-establish a backup of the restored store and then
confirm: `syllabus ops backup` (the restored store has an `ops.restore`
receipt but no backup receipt until it is backed up again — ADR 012,
Decision 4), then `syllabus ledger verify` and `syllabus ops status`
— both must be green before new ingestion or generation resumes (ADR
012, Decision 6).

## What "failed" looks like

- `Error: no backup at ...` — the `--backup` path is wrong. Check the
  path; the backup must be a file produced by `syllabus ops backup`.
- `Error: backup failed verification and was not restored: ...` — the
  backup is corrupt or truncated. Do not force it: pick an older
  backup and verify that one instead. The live store is untouched.
- `Error: restored store failed verification on the live path: ...` —
  the swap happened but the live path does not verify. Stop, keep the
  backup file, and treat the live store as suspect: do not ingest or
  generate until the cause is found.
- A receipt whose `backup_sha256` does not match `sha256sum` of the
  backup file — the file changed between verification and restore. Do
  not trust that restore; re-run it from a fresh copy of the backup.

## Drill

On synthetic data only: build a scratch store, back it up, delete the
store file, restore from the backup, and confirm `plan show` returns
the plan. The test suite runs this drill on every CI run
(`tests/test_operating_readiness.py`). The operator's drill on a real
store is the same commands with the real paths — and a real store is
never the drill's scratch data.
