# Documentation audit truth contract

The audit discovers intentions; it does not verify delivery. Report schema 2.0
separates `implementation_claims` from `implementation_tags` and marks discovered
items `verification_status: unverified`. The legacy `planned` value means pending
verification/disposition, not proof that the implementation is absent.

Keyword matches and milestone status YAML are historical claims only. Neither
promotes an item to implemented, even if a status file lists evidence paths.
Unknown claimed IDs remain in `unmatched_implementation_claims`; they do not
create new requirements. Existing stable IDs and original source references stay
intact. `implemented_count` counts verified items (currently zero), while milestone
`completion_pct` is null because progress cannot honestly be inferred here.

Generated audit reports and execution plans remain ingested and inventoried, but
are excluded from intention extraction. Known legacy output paths are recognized;
new Markdown outputs carry an explicit marker and JSON outputs an artifact kind.
Unmarked copies of older generated outputs at arbitrary paths still need archival
classification; detection is not a semantic classifier. Historical artifacts are
preserved and must not be treated as current truth.

A future completion verifier (#37) must bind an intention and acceptance criteria
to the repository, exact default-branch commit, successful executed checks and
review/disposition evidence. It must reject unknown IDs, missing checks, stale
heads and self-declared receipts. Until that authenticated contract exists, this
audit deliberately cannot certify completion. Local tests are evidence about a
candidate, not proof of delivery on default.

Regression coverage exercises keyword false positives, unsupported status claims,
unknown IDs and generated-report feedback. See #38 for ownership and #21 for
sequencing. This contract does not change the historical issue ledger.
