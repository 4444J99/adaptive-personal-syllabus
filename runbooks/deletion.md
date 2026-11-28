# Runbook: deletion

Owner: Anthony James Padavano (4444J99) — the repo owner-operator.
Decision: ADR 012 (Decision 12). Issue: #58 (MTR-027).

## Purpose

Delete one learner profile and its dependent plans from the store,
with a receipt that proves the deletion without re-persisting the
personal data it deletes.

## Command

```sh
syllabus ops delete-profile <profile-id> \
  --db-path ~/.adaptive-syllabus/adaptive_syllabus.db
```

Find the profile id first: profile ids are the `id` column of the
`profiles` table (e.g. `sqlite3 <store> "SELECT id, name FROM
profiles;"` — run that on a copy, not the live store, if the store is
in active use).

## Expected output

A JSON receipt, exit code 0:

```json
{
  "operation": "delete-profile",
  "profile_id": 3,
  "profiles_deleted": 1,
  "plans_deleted": 2
}
```

The receipt carries counts only — no name, goals, or context. An
`ops.delete-profile` ledger event records the same counts.

## What is deleted, and what is not

- Deleted: the profile row, its plans, the plans' modules and stored
  payloads. (Stored payloads are deleted explicitly first:
  `plan_payloads` has no `ON DELETE CASCADE`.)
- Not deleted: the `profile.init` ledger event for the profile. The
  ledger is append-only (#52); the deletion receipt explains the
  deletion instead of rewriting history.
- Not deleted: the profile file, if one was written by `syllabus
  profile init` (default `~/.adaptive-syllabus/profile.json`). Delete
  that file yourself — this command covers the database record only.
- Not deleted: backups taken before the deletion still contain the
  record until those backups are rotated. Rotate backups after a
  deletion if the record must be gone everywhere.

## What "failed" looks like

- `Error: no profile with id ...` — the id does not exist. Nothing
  was deleted. Check the id and re-run.
- `Error: store at ... failed to open: ...` — the store is unreadable.
  Restore from the last verified backup first (see `runbooks/restore.md`),
  then delete.
- A receipt with `plans_deleted` that does not match the plans you
  expected — stop and check the profile id before deleting anything
  else. The ledger event records what was actually deleted.
