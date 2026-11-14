# Plan integrity v2: identity, persistence and review

## Identity

Fingerprint version 2 hashes canonical compact JSON containing the complete supplied profile, complete generated module payload, snapshot ID, sorted snapshot content hashes, and personalization-rules hash. Mapping order is immaterial; list order is meaningful. NaN and infinities fail before plan writes. The full 64-character SHA-256 is stored alongside the 12-character display prefix. The short prefix has only 48 bits and is neither a database primary key, security token nor collision-proof identity. Every persisted generation gets a separate integer DB key, including identical replay or colliding prefixes.

Consumers audited: plan JSON/text/Markdown renderers display the prefix; ledger uses it as descriptive metadata; `plan show`, artifacts and chamber hooks use the integer database key. The separate legacy generators use their own IDs and do not read the versioned payload.

Compare identities only when fingerprint versions match, using the full digest where available. Different versions are incomparable, not evidence of different learning. Historical prefixes cannot reconstruct full hashes. Changes to generated instructional fields intentionally change v2 fingerprints.

## Additive migration and historical records

Opening Storage adds `plan_payloads` and `source_judgments`. No historical plan is rehashed or overwritten. New plans write the profile projection, plan row, module rows and complete serialized payload in one SQLite transaction. There is no short-ID upsert. `Storage.get_plan(integer)` / `syllabus plan show INTEGER` returns that exact payload. Original v1 records predate full-payload storage: retrieval explicitly returns `legacy_projection`, original persisted fields and a missing-original-payload notice; it never invents an original fingerprint, prerequisites or adaptation records.

The existing older snapshot-binding migration remains unchanged. Back up a historical database before opening it if preserving its pre-existing unbound-snapshot representation is required.

## Rollback

1. Stop writers and back up the entire SQLite database with SQLite's backup API.
2. Roll back application code to the chosen historical revision; leave both additive tables intact.
3. The older reader continues to see the compatible plan/module projections of both generations. It cannot expose newer integrity fields.
4. Restore current code to retrieve the intact v2 payloads. Never drop the additive tables or restore an older backup over newer writes as a code rollback.

Tests exercise old and new rows coexisting, unchanged historical rows, historical projection reads, and reopening current storage. No live personal database was migrated.

## Source support and adaptation

Candidates rank module-title terms against once-loaded, once-tokenized corpus chunks. Generic generated-question words do not rank candidates. This simple candidate selector is not semantic entailment and can miss synonyms. It loads the complete snapshot once; returned candidates are limited to three per module.

Locators bind snapshot, document content hash and chunk index, plus a chunk-text digest. Text extraction is not human inspection. Whole-document completeness remains not established, including excerpts. Duplicate payload aliases and distinct same-name documents retain their identities. Stored text remains inspectable after an external file disappears; absent/binary chunks fail closed.

Judgments append separately after exact passage matching and explicit reviewer attribution. No automatic source-content execution or manufactured human judgment exists. Contradictory judgments remain visible. Immutable plans are not silently updated after review.

Actual encounter steps change for relevant purpose, prior task evidence, medium, prerequisites and access. Irrelevant profile fields may change input identity but leave instruction unchanged. Unassessed is not beginner. Assistant explanations are labeled; source argument, analogy, critique and learner words have separate fields. A self-contained numerical example allows a phone route without library access; it does not purport to teach every source topic.

## Outputs

Wings selection yields descriptors only. A separate artifact command writes an explicitly assistant-authored local working sheet for one selected Wing, refusing overwrite. A separate authorization command records the exact file digest and destination; there is no publication transport. No selection, descriptor, generation, authorization or explanation is evidence of learner performance.
