# Live-source refresh (MTR-018, #54)

> **Status of this plan:** This is one take, not a solidified plan. It is my current version of what I think should work, based on the source verified at the head named in the plan, and it needs further investigation and further hardening before and during implementation. Each step includes my reasoning for why, so the plan can be checked rather than trusted; where live evidence disagrees with the plan, the evidence wins and the plan gets revised.

Implements #54 (MTR-018) at main `96459abc` (loop PR, branch
`work/mentor/live-source-loop`): `corpus refresh` re-reads the live source
and records one outcome per source, so a plan built from a stale snapshot
says so instead of silently presenting old passages as current.

## The defect, verified at the head

Ingest was a one-shot snapshot: each `corpus ingest` run minted a brand-new
snapshot with brand-new document rows, and nothing recorded freshness,
change, deletion, failure, or recovery. The planner read the latest
snapshot blindly. Reproduced at `96459abc` (synthetic one-file corpus):
change the file and re-ingest, and a second document row appears with no
link to the first and no "changed" record; delete the file and re-ingest,
and the deletion leaves no marker anywhere.

## Decisions (recorded, plan step 2)

- **First source:** the local ingest root already used by `corpus ingest`.
  *Why:* it is the authorized, available source; any remote fetcher is a
  later adapter, not this build. No new access is needed, no private data
  is involved.
- **Freshness bound:** per-source `max_age_hours`, default 168 (7 days),
  stored on the source record and settable per source via
  `corpus refresh --max-age-hours`. *Why:* a bound has to live with the
  source it judges (different sources go stale at different rates), and a
  run flag is the operator's way to set it without a second command.
- **Trigger:** operator run of `corpus refresh`; a scheduled invocation is
  the scheduled form. *Why:* no daemon in this build — the refresh is a
  command the operator (or their scheduler) runs, and the run itself is
  the evidence.
- **Source identity:** `(root_path, rel_path)`, one `source_records` row.
  *Why:* the identity must survive across snapshots, and the rel path
  inside a root is the stable name for a local source; the root scopes it.

## What a refresh records

`source_versions` is append-only. One row per content version
(`ok` / `changed`), plus one marker row per failure / deletion /
revocation observation (`timeout` / `rate_limited` / `error` /
`deleted` / `revoked`, `sha256` NULL — the bytes were not read, or the
file was gone). `refresh_runs` records one row per invocation with its
outcome counts, and one `corpus.refresh` ledger event carries the counts
plus the per-source outcomes in the same transaction as the version rows.

- **Same bytes, healthy lineage (`unchanged`):** no new version row
  (idempotent replay), but the version's `retrieved_at` advances to this
  read. *Why:* the plan's "no new version" is kept, and a just-confirmed
  source must not false-positive stale on age alone.
- **Changed bytes (`changed`):** a new version under the same source id.
  The stored document row keeps the old bytes — a refresh never rewrites
  snapshots or documents, so the new content enters the planner only via
  a fresh `corpus ingest`. *Why:* rewriting history would destroy the
  provenance the refresh exists to protect; the freshness state is what
  tells the planner the snapshot is behind.
- **Recovery after a marker:** a new version row even when the bytes match
  the last good version, with `recovered_after` in the detail. *Why:* the
  marker it supersedes stays in history, and the recovery is itself an
  observation worth recording.
- **One source's failure never aborts the refresh:** `timeout` /
  `rate_limited` / `error` are recorded for that source and the refresh
  continues; the prior version stays usable-but-stale with its last-good
  `retrieved_at`. *Why:* this is the deliberate inverse of ingest, where
  one unreadable file aborts everything — a refresh that dies on the
  first failure reports nothing about the rest.

## Freshness states (what consumers report)

`fresh` (re-read within the bound) / `stale` (bytes changed since ingest,
or last good retrieval older than the bound) / `missing` (latest
observation `deleted`) / `failed` (latest observation `timeout` /
`rate_limited` / `error`) / `revoked` (latest observation `revoked`) /
`unknown` (ingested but never refreshed).

Consumers: planner candidates carry the state in the plan's top-level
`source_freshness` block (never inside the fingerprint — freshness is
time-varying observation, not plan content); `corpus stats` reports
per-source freshness for the selected snapshot; `corpus passage` reports
it for the passage's source. `missing` and `revoked` sources are excluded
from planner candidates and named in `excluded_sources`; a plan built
from a stale snapshot carries `stale_snapshot: true`.

## Scoping against #48 and #50 (not built here)

- **Admission (#48):** refresh runs only over admitted sources, and the
  admission gate at this head is the merged containment +
  privacy-classification guard in `discover_documents` (#33/#34). A file
  present but inventory-refused is recorded `revoked`, not silently
  skipped. #48's full admission record (owner / license / admitted-by /
  `corpus admit` / `corpus revoke`) is a separate build and is not folded
  in here.
- **Support (#50):** refresh never promotes a candidate to support. Only
  a human judgment does that; every candidate stays
  `source_support_unverified` however fresh its source is.

## What this build does not do

- No remote fetcher, no daemon/scheduler, no `corpus admit`/`revoke`.
- No re-ingest: changed content is recorded, not applied — apply it with
  `corpus ingest`.
- No signature scheme, no new credential, no private data in any receipt.
