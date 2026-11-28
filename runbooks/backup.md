# Runbook: backup

Owner: Anthony James Padavano (4444J99) — the repo owner-operator.
Decision: ADR 012 (Decisions 4, 5, 10). Issue: #58 (MTR-027).

## Purpose

Copy the live SQLite store to a named location with a checksum receipt,
so a later restore has something verified to restore from. A backup is
taken with the SQLite backup API, not a raw file copy: a copy taken
while a writer holds the database can be torn, and a torn backup is
worse than no backup because it looks like evidence.

## Command

```sh
syllabus ops backup --db-path ~/.adaptive-syllabus/adaptive_syllabus.db \
  --output ~/backups/adaptive-syllabus-2026-11-28.db
```

(Use any `--output` path outside the repo and outside git. The default
`--db-path` is the live store; pass it explicitly only when the store
lives elsewhere.)

## Expected output

A JSON receipt, exit code 0:

```json
{
  "operation": "backup",
  "db_path": ".../adaptive_syllabus.db",
  "backup_path": ".../adaptive-syllabus-2026-11-28.db",
  "sha256": "<64 hex chars>",
  "bytes": 123456,
  "source_head_hash": "<ledger head at backup time>",
  "source_event_count": 42
}
```

The receipt is also appended to the live ledger as an `ops.backup`
event, so `syllabus ops status` can read back how fresh the last
backup is. The backup file itself does not contain its own receipt
event — it is a faithful copy of the store at backup time.

## Verify the backup

```sh
sha256sum <backup file>   # must equal the receipt's sha256
```

Or copy the backup aside and run `syllabus ledger verify --db-path
<copy>` — it must print `"ok": true`. Never verify against the backup
file in place with a command that could write to it; verify a copy.

## What "failed" looks like

- `Error: no store at ...` — the `--db-path` is wrong or the store was
  never created. Check the path; `syllabus profile init` creates the
  store on first use.
- `Error: backup output must not be the live store itself` — the
  `--output` equals the live store. Pick a different path.
- A receipt whose `sha256` does not match `sha256sum` of the file —
  the backup is not trustworthy. Delete it, re-run the backup, and do
  not restore from it.

## Cadence

At least once a week: `ops status` fails when the last backup receipt
is older than 168 hours (ADR 012, Decision 4). Backups age out when
the operator rotates them; a deleted profile stays in backups taken
before its deletion until those backups are rotated — that is expected,
and it is why the deletion runbook names rotation explicitly.
