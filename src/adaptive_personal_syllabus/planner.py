"""Profile-aware planning that merges learner context with corpus evidence."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from .admission import redact_rel_path
from .encounter import adapt_encounter
from .freshness import EXCLUDED_STATES, summarize_snapshot_freshness
from .generator import SyllabusGenerator
from .ledger import Ledger
from .models import DifficultyLevel, LearnerProfile, PersonalizationRule
from .storage import Storage
from .support import summarize_judgments, worst_support_status

WINGS: list[dict[str, str]] = [
    {
        "wing_id": "academic",
        "name": "Academic",
        "description": "Research summary or formal analysis.",
    },
    {"wing_id": "sop", "name": "SOP", "description": "Operational runbook or procedure."},
    {
        "wing_id": "business",
        "name": "Business",
        "description": "Business framing and value proposition.",
    },
    {"wing_id": "social", "name": "Social", "description": "Public-facing social content."},
    {
        "wing_id": "community",
        "name": "Community",
        "description": "Community prompt and collaboration seed.",
    },
    {"wing_id": "wiki", "name": "Wiki", "description": "Reference documentation artifact."},
    {"wing_id": "web_blog", "name": "Web/Blog", "description": "Long-form narrative publication."},
    {"wing_id": "grants", "name": "Grants", "description": "Grant-aligned research framing."},
]

FINGERPRINT_SCHEMA_VERSION = 2
SOURCE_SELECTION_SCHEMA_VERSION = 1


def _validate_finite_json(value: Any, path: str = "$") -> None:
    """Reject values that JSON accepts but portable JSON and stable hashes do not."""
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"Non-finite JSON number at {path}")
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise TypeError(f"Non-string JSON object key at {path}")
            _validate_finite_json(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _validate_finite_json(child, f"{path}[{index}]")


def _tokens(*values: Any) -> set[str]:
    text = " ".join(str(value) for value in values)
    return {token for token in re.findall(r"[a-z0-9]+", text.lower()) if len(token) > 2}


DEFAULT_PERSONALIZATION_RULES: list[PersonalizationRule] = [
    PersonalizationRule(
        rule_id="purpose_and_access",
        description="Choose explicit encounter instructions without rewriting source arguments.",
        profile_fields=["learning_purpose", "medium", "access_conditions"],
    ),
    PersonalizationRule(
        rule_id="task_evidence_route",
        description="Choose a task route from matching prior observations, retaining uncertainty.",
        profile_fields=["prior_task_evidence"],
    ),
]


class Planner:
    """Generate persisted, profile-aware plans with stable JSON output."""

    def __init__(self, storage: Storage, ledger: Ledger, seed_dir: Path | None = None) -> None:
        self.storage = storage
        self.ledger = ledger
        self.seed_dir = seed_dir

    @staticmethod
    def _load_profile(profile_path: Path) -> dict[str, Any]:
        data = json.loads(profile_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Profile must be an object")  # noqa: TRY004
        if "name" not in data:
            raise ValueError("Profile must include 'name'")
        return data

    @staticmethod
    def _hash_personalization_rules(rules: list[PersonalizationRule]) -> str:
        blob = json.dumps(
            [
                {
                    "rule_id": r.rule_id,
                    "description": r.description,
                    "profile_fields": r.profile_fields,
                    "module_filters": r.module_filters,
                }
                for r in rules
            ],
            sort_keys=True,
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    @staticmethod
    def _full_fingerprint(
        profile_data: dict[str, Any],
        modules: list[dict[str, Any]],
        *,
        snapshot_id: int,
        evidence_sha256: list[str],
        personalization_rules_hash: str,
    ) -> str:
        payload = {
            "fingerprint_schema_version": FINGERPRINT_SCHEMA_VERSION,
            "profile": profile_data,
            "modules": modules,
            "snapshot_id": snapshot_id,
            "evidence_sha256": evidence_sha256,
            "personalization_rules_hash": personalization_rules_hash,
        }
        _validate_finite_json(payload)
        blob = json.dumps(payload, sort_keys=True, allow_nan=False, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    @staticmethod
    def _deterministic_plan_uid(*args: Any, **kwargs: Any) -> str:
        return Planner._full_fingerprint(*args, **kwargs)[:12]

    @staticmethod
    def _select_source_candidates(
        *, chunks: list[tuple[dict[str, Any], set[str]]], module: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Rank module-specific text; retrieval never establishes claim support."""
        query = _tokens(module["title"])
        candidates = [(len(query & tokens), chunk) for chunk, tokens in chunks if query & tokens]
        candidates.sort(
            key=lambda item: (-item[0], item[1]["canonical_path"], item[1]["chunk_index"])
        )
        return [
            {
                "snapshot_id": int(chunk["snapshot_id"]),
                "document_id": int(chunk["document_id"]),
                "canonical_path": str(chunk["canonical_path"]),
                "rel_path": str(chunk["rel_path"]),
                "sha256": str(chunk["sha256"]),
                "locator": f"chunk:{int(chunk['chunk_index'])}",
                "heading_path": str(chunk["heading_path"]),
                "passage_sha256": hashlib.sha256(chunk["text"].encode()).hexdigest(),
                "inspection_status": "text_available_not_reviewed",
                "selection_status": "lexical_relevance_candidate",
                "source_support": "source_support_unverified",
                "reviewer_status": "not_reviewed",
                "judgment_method": None,
                # Source admission (#48): only admitted, passage-kind
                # documents reach this method at all (see generate);
                # the stamps say so, and completeness is computed from
                # the stored state instead of hard-coded.
                "admission_status": "admitted",
                "content_kind": str(chunk.get("content_kind") or "passage"),
                "document_completeness": "complete",
            }
            for _, chunk in candidates[:3]
        ]

    def generate(self, profile_path: Path) -> dict[str, Any]:
        profile_path = profile_path.expanduser().resolve()
        profile_data = self._load_profile(profile_path)
        _validate_finite_json(profile_data)
        self.ledger.append(
            "profile.load",
            {
                "profile_path": str(profile_path),
                "name": profile_data.get("name"),
                "organs_of_interest": profile_data.get("organs_of_interest", []),
            },
        )

        level = DifficultyLevel(profile_data.get("level", "unassessed"))
        learner = LearnerProfile(
            name=str(profile_data["name"]),
            organs_of_interest=list(profile_data.get("organs_of_interest", [])),
            level=level,
            completed_modules=list(profile_data.get("completed_modules", [])),
        )

        generator = SyllabusGenerator(seed_dir=self.seed_dir)
        path = generator.generate(learner)

        snapshot = self.storage.latest_snapshot()
        if snapshot is None:
            raise ValueError("No corpus snapshot found. Run 'syllabus corpus ingest' first.")
        snapshot_id = int(snapshot["id"])

        evidence_sha256 = self.storage.list_snapshot_sha256(snapshot_id=snapshot_id)
        output_policy = profile_data.get("output_policy", {})
        if not isinstance(output_policy, dict):
            raise ValueError("output_policy must be an object")  # noqa: TRY004 -- public validation API
        selected_wings = output_policy.get("selected_wings", [])
        valid_wings = {wing["wing_id"] for wing in WINGS}
        if not isinstance(selected_wings, list) or any(
            not isinstance(wing, str) or wing not in valid_wings for wing in selected_wings
        ):
            raise ValueError("output_policy.selected_wings must be a list of known wing IDs")

        module_rows: list[dict[str, Any]] = []
        for seq, m in enumerate(path.modules, start=1):
            module_rows.append(
                {
                    "seq": seq,
                    "module_id": m.module_id,
                    "title": m.title,
                    "organ": m.organ,
                    "difficulty": m.difficulty.value,
                    "estimated_hours": m.estimated_hours,
                    "readings": m.readings,
                    "questions": m.questions,
                    "prerequisites": m.prerequisites,
                    "artifact_descriptors": [
                        wing for wing in WINGS if wing["wing_id"] in selected_wings
                    ],
                }
            )
        chunks = [
            (chunk, _tokens(chunk["heading_path"], chunk["text"]))
            for chunk in self.storage.list_document_chunks(snapshot_id=snapshot_id)
        ]
        # Live-source refresh (#54): freshness is time-varying observation,
        # so it never enters the plan fingerprint — but selection must not
        # draw on sources the last refresh found missing or revoked, and
        # the plan must say when it was built from a stale snapshot. The
        # exclusion changes the candidate list (and therefore the plan);
        # the per-source states live in the top-level `source_freshness`
        # block added after the fingerprint, alongside the snapshot block.
        freshness = summarize_snapshot_freshness(self.storage, snapshot_id=snapshot_id)
        fresh_by_doc = {
            int(item["document_id"]): item for item in freshness["sources"]
        }
        # Source admission (#48): a candidate must be admitted, passage
        # kind, and not private-access. Admission answers "may this
        # source be used"; it never promotes a candidate to support.
        # The map is read before both exclusion passes so a private
        # path is redacted in the freshness exclusions as well.
        admission_map = self.storage.admission_map_for_snapshot(snapshot_id)
        excluded_sources: list[dict[str, Any]] = []
        excluded_doc_ids: set[int] = set()
        usable_chunks = []
        for chunk, tokens in chunks:
            doc_id = int(chunk["document_id"])
            state = fresh_by_doc.get(doc_id, {}).get("state", "unknown")
            if state in EXCLUDED_STATES:
                if doc_id not in excluded_doc_ids:
                    excluded_doc_ids.add(doc_id)
                    access = admission_map.get(doc_id, {}).get("access")
                    excluded_sources.append(
                        {
                            "document_id": doc_id,
                            "rel_path": redact_rel_path(str(chunk["rel_path"]), access),
                            "state": str(state),
                            "reason": str(fresh_by_doc[doc_id].get("reason")),
                        }
                    )
                continue
            usable_chunks.append((chunk, tokens))
        chunks = usable_chunks
        excluded_admission: list[dict[str, Any]] = []
        excluded_admission_ids: set[int] = set()
        usable_chunks = []
        for chunk, tokens in chunks:
            doc_id = int(chunk["document_id"])
            state = admission_map.get(doc_id, {"status": "unadmitted", "access": None})
            kind = str(chunk.get("content_kind") or "passage")
            if state["status"] != "admitted" or kind != "passage" or state.get("access") == "private":
                if doc_id not in excluded_admission_ids:
                    excluded_admission_ids.add(doc_id)
                    if state.get("access") == "private":
                        reason = "private_access"
                    elif state["status"] != "admitted":
                        reason = f"admission_{state['status']}"
                    else:
                        reason = "metadata_only"
                    excluded_admission.append(
                        {
                            "document_id": doc_id,
                            "rel_path": redact_rel_path(
                                str(chunk["rel_path"]), state.get("access")
                            ),
                            "reason": reason,
                        }
                    )
                continue
            usable_chunks.append((chunk, tokens))
        chunks = usable_chunks
        # Claim support (#50, step 5): judgments for this snapshot, attached
        # to the modules that actually selected their documents. Modules
        # carry no claim strings, so the checkable filter is the module's
        # selected sources — a judgment about a source the module did not
        # select is not attached to it. Judgments enter the fingerprint:
        # they are plan content, not time-varying observation like
        # freshness, so a plan whose evidence changes is a different plan.
        snapshot_judgments = self.storage.list_source_judgments(
            snapshot_id=snapshot_id
        )
        for row in module_rows:
            row["adaptation"], row["encounter"] = adapt_encounter(profile_data, row)
            candidates = self._select_source_candidates(chunks=chunks, module=row)
            candidate_doc_ids = {int(c["document_id"]) for c in candidates}
            attached = [
                j
                for j in snapshot_judgments
                if int(j["document_id"]) in candidate_doc_ids
                and j.get("status") != "superseded"
            ]
            superseded = [
                j
                for j in snapshot_judgments
                if int(j["document_id"]) in candidate_doc_ids
                and j.get("status") == "superseded"
            ]
            claim_statuses = [
                summarize_judgments(attached, str(claim))["status"]
                for claim in {str(j["claim"]) for j in attached}
            ]
            row["source_selection"] = {
                "schema_version": SOURCE_SELECTION_SCHEMA_VERSION,
                "candidates": candidates,
                "claim_support_status": (
                    worst_support_status(claim_statuses)
                    if attached
                    else "source_support_unverified"
                ),
                "judgments": attached,
                # Superseded judgments are history, not evidence: listed
                # so a reader can see support existed and was invalidated,
                # never counted toward the live status above.
                "superseded_judgments": superseded,
                "missing_support": (
                    None
                    if attached
                    else "No human-reviewed claim support is attached."
                ),
            }

        personalization_rules_hash = self._hash_personalization_rules(
            DEFAULT_PERSONALIZATION_RULES
        )
        full_digest = self._full_fingerprint(
            profile_data,
            module_rows,
            snapshot_id=snapshot_id,
            evidence_sha256=evidence_sha256,
            personalization_rules_hash=personalization_rules_hash,
        )

        plan_uid = full_digest[:12]
        # Freshness of the sources this plan actually drew on, plus the
        # snapshot-wide counts. Added after the fingerprint on purpose:
        # freshness is a time-varying observation, not plan content, and
        # must not make the fingerprint drift with the clock. A plan built
        # from a stale snapshot says so here (`stale_snapshot: true`) and
        # names the excluded sources, so stale passages are never silently
        # presented as current.
        candidate_doc_ids = {
            int(candidate["document_id"])
            for row in module_rows
            for candidate in row["source_selection"]["candidates"]
        }
        plan_freshness = {
            "snapshot_id": snapshot_id,
            "stale_snapshot": bool(freshness["stale_snapshot"]),
            "summary": freshness["summary"],
            "excluded_sources": excluded_sources,
            "sources": [
                item for item in freshness["sources"] if int(item["document_id"]) in candidate_doc_ids
            ],
        }
        # Source admission (#48): which documents were kept out of
        # selection by the admission decision, and why. Added after the
        # fingerprint like freshness: the decision can change without
        # the plan's modules changing, and the exclusion list is the
        # evidence that unadmitted sources never reached a candidate.
        admission_summary: dict[str, int] = {"unadmitted": 0, "admitted": 0}
        for state in admission_map.values():
            key = str(state["status"])
            admission_summary[key] = admission_summary.get(key, 0) + 1
            if state.get("access") == "private":
                admission_summary["private_access"] = (
                    admission_summary.get("private_access", 0) + 1
                )
        plan_admission = {
            "snapshot_id": snapshot_id,
            "summary": admission_summary,
            "excluded_sources": excluded_admission,
        }
        plan: dict[str, Any] = {
            "schema_version": "2.0",
            "plan_id": plan_uid,
            "fingerprint_sha256": full_digest,
            "db_plan_id": None,
            "title": f"Learning Path: {', '.join(learner.organs_of_interest)}",
            "profile": {
                "name": learner.name,
                "organs_of_interest": learner.organs_of_interest,
                "level": learner.level.value,
                "goals": list(profile_data.get("goals", [])),
                "context": {},
                "completed_modules": learner.completed_modules,
            },
            "snapshot": snapshot,
            "source_freshness": plan_freshness,
            "source_admission": plan_admission,
            "determinism_inputs": {
                "fingerprint_schema_version": FINGERPRINT_SCHEMA_VERSION,
                "snapshot_id": snapshot_id,
                "evidence_sha256": evidence_sha256,
                "personalization_rules_hash": personalization_rules_hash,
            },
            "personalization_rules": [
                {
                    "rule_id": r.rule_id,
                    "description": r.description,
                    "profile_fields": r.profile_fields,
                    "module_filters": r.module_filters,
                }
                for r in DEFAULT_PERSONALIZATION_RULES
            ],
            "output_policy": {
                "selected_wings": selected_wings,
                "publication_authorized": False,
                "encounter_only": not selected_wings,
            },
            "modules": module_rows,
            "totals": {
                "module_count": len(module_rows),
                "total_hours": path.total_hours,
            },
        }

        db_plan_id = None
        with self.storage.connection() as conn:
            # The plan row and its plan.generate event share one
            # transaction (#52, MTR-022): a crash between them can no
            # longer leave state without its ledger event, or an event
            # without its state. The profile.load event above stays
            # outside it: it records a read, not a state write, so
            # there is no transaction for it to share.
            db_plan_id = self.storage.insert_complete_plan(plan, conn=conn)
            plan["db_plan_id"] = db_plan_id

            self.ledger.append(
                "plan.generate",
                {
                    "plan_id": plan_uid,
                    "db_plan_id": db_plan_id,
                    "snapshot_id": snapshot_id,
                    "module_count": len(module_rows),
                    "total_hours": path.total_hours,
                    "evidence_hash_count": len(evidence_sha256),
                },
                conn=conn,
            )

        return plan
