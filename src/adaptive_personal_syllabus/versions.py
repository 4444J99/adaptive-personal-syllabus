"""Single source of truth for every schema-version literal (ADR 008, #53).

Each public JSON shape the package emits carries a schema version in its own
namespace. The literals used to live as bare strings scattered across
core.py, planner.py, corpus.py, storage.py, encounter.py and docs_audit.py,
so a bump in one place could not be found from any other. Every emitter
imports its constant from here; the compatibility matrix in ADR 008 names
each namespace, its current value, and the rule for when it bumps.

Two version families already live as constants in planner.py and stay
there: FINGERPRINT_SCHEMA_VERSION (int 2) and SOURCE_SELECTION_SCHEMA_VERSION
(int 1). This module does not re-declare them.
"""

# Plan JSON emitted by Planner.generate (planner.py). "2.0" since the
# fingerprint / source-selection passes (#52/#54); bump on any breaking
# plan-schema change, with a migration note (ADR 008).
PLAN_SCHEMA_VERSION = "2.0"

# CLI JSON envelopes: corpus ingest / refresh / stats, ledger verify,
# profile-init echo, chamber run. One envelope namespace, "1.0" everywhere
# it is used; bump only when an envelope field is removed or renamed.
CLI_ENVELOPE_SCHEMA_VERSION = "1.0"

# Learner profile document (profile init). "1.0"; bump when a profile field
# is removed, renamed, or gains a new required meaning.
PROFILE_SCHEMA_VERSION = "1.0"

# Encounter decision document (encounter.py). "1.2"; bump on any breaking
# change to the decision shape.
ENCOUNTER_SCHEMA_VERSION = "1.2"

# Milestone execution plan built by docs_audit.build_milestone_execution_plan.
# "1.0"; bump when the execution-plan shape breaks.
MILESTONE_EXECUTION_PLAN_SCHEMA_VERSION = "1.0"

# Docs-audit report (docs_audit.py). "2.0" since the milestone-execution
# shape changed first; bump only when the report shape itself breaks.
AUDIT_REPORT_SCHEMA_VERSION = "2.0"

# Legacy projection marker: Storage.get_plan returns this value when a plan
# predates stored payloads, so a reader can tell a reconstructed plan from
# a stored one. It is a marker, not a version; it never bumps.
LEGACY_PROJECTION_SCHEMA_VERSION = "legacy_projection"

# SQLite store schema version (storage.py schema_meta table). 1 is the first
# marked version: every database created before the marker has exactly this
# shape. Bump with a migration in Storage._run_migrations (ADR 008).
DB_SCHEMA_VERSION = 1
