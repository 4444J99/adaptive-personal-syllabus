"""Profile-aware planning that merges learner context with corpus evidence."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .generator import SyllabusGenerator
from .ledger import Ledger
from .models import DifficultyLevel, LearnerProfile, PersonalizationRule
from .storage import Storage

WINGS: list[dict[str, str]] = [
    {"wing_id": "academic", "name": "Academic", "description": "Research summary or formal analysis."},
    {"wing_id": "sop", "name": "SOP", "description": "Operational runbook or procedure."},
    {"wing_id": "business", "name": "Business", "description": "Business framing and value proposition."},
    {"wing_id": "social", "name": "Social", "description": "Public-facing social content."},
    {"wing_id": "community", "name": "Community", "description": "Community prompt and collaboration seed."},
    {"wing_id": "wiki", "name": "Wiki", "description": "Reference documentation artifact."},
    {"wing_id": "web_blog", "name": "Web/Blog", "description": "Long-form narrative publication."},
    {"wing_id": "grants", "name": "Grants", "description": "Grant-aligned research framing."},
]


DEFAULT_PERSONALIZATION_RULES: list[PersonalizationRule] = [
    PersonalizationRule(
        rule_id="contextual_rewrite",
        description="Rewrite generic recommendations using learner goals and context.",
        profile_fields=["goals", "context"],
    ),
    PersonalizationRule(
        rule_id="difficulty_alignment",
        description="Align module framing with learner difficulty level and completed modules.",
        profile_fields=["level", "completed_modules"],
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
    def _deterministic_plan_uid(
        profile_data: dict[str, Any],
        modules: list[dict[str, Any]],
        *,
        snapshot_id: int,
        evidence_sha256: list[str],
        personalization_rules_hash: str,
    ) -> str:
        blob = json.dumps(
            {
                "profile": {
                    "name": profile_data.get("name"),
                    "organs_of_interest": profile_data.get("organs_of_interest", []),
                    "level": profile_data.get("level", "beginner"),
                    "goals": profile_data.get("goals", []),
                },
                "modules": [
                    {
                        "module_id": m["module_id"],
                        "title": m["title"],
                        "organ": m["organ"],
                        "difficulty": m["difficulty"],
                    }
                    for m in modules
                ],
                "snapshot_id": snapshot_id,
                "evidence_sha256": evidence_sha256,
                "personalization_rules_hash": personalization_rules_hash,
            },
            sort_keys=True,
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]

    def generate(self, profile_path: Path) -> dict[str, Any]:
        profile_path = profile_path.expanduser().resolve()
        profile_data = self._load_profile(profile_path)
        self.ledger.append(
            "profile.load",
            {
                "profile_path": str(profile_path),
                "name": profile_data.get("name"),
                "organs_of_interest": profile_data.get("organs_of_interest", []),
            },
        )

        level = DifficultyLevel(profile_data.get("level", "beginner"))
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

        evidence_docs = self.storage.list_documents(snapshot_id=snapshot_id, limit=5)
        evidence_sha256 = self.storage.list_snapshot_sha256(snapshot_id=snapshot_id)
        evidence_refs = [
            {
                "document_id": int(d["id"]),
                "canonical_path": str(d["canonical_path"]),
                "rel_path": str(d["rel_path"]),
                "sha256": str(d["sha256"]),
            }
            for d in evidence_docs
        ]

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
                    "artifact_descriptors": WINGS,
                    "evidence": evidence_refs[:3],
                }
            )

        personalization_rules_hash = self._hash_personalization_rules(DEFAULT_PERSONALIZATION_RULES)
        plan_uid = self._deterministic_plan_uid(
            profile_data,
            module_rows,
            snapshot_id=snapshot_id,
            evidence_sha256=evidence_sha256,
            personalization_rules_hash=personalization_rules_hash,
        )

        profile_id = self.storage.insert_profile(
            name=learner.name,
            level=learner.level.value,
            goals=list(profile_data.get("goals", [])),
            context=dict(profile_data.get("context", {})),
        )
        db_plan_id = self.storage.insert_plan(
            profile_id=profile_id,
            title=f"Learning Plan {plan_uid}",
            total_hours=path.total_hours,
            module_count=len(module_rows),
            snapshot_id=snapshot_id,
        )

        for row in module_rows:
            self.storage.insert_plan_module(
                plan_id=db_plan_id,
                seq=int(row["seq"]),
                module_id=str(row["module_id"]),
                title=str(row["title"]),
                organ=str(row["organ"]),
                difficulty=str(row["difficulty"]),
                readings=list(row["readings"]),
                questions=list(row["questions"]),
                estimated_hours=float(row["estimated_hours"]),
            )

        plan = {
            "schema_version": "1.0",
            "plan_id": plan_uid,
            "db_plan_id": db_plan_id,
            "title": f"Learning Path: {', '.join(learner.organs_of_interest)}",
            "profile": {
                "name": learner.name,
                "organs_of_interest": learner.organs_of_interest,
                "level": learner.level.value,
                "goals": list(profile_data.get("goals", [])),
                "context": dict(profile_data.get("context", {})),
                "completed_modules": learner.completed_modules,
            },
            "snapshot": snapshot,
            "determinism_inputs": {
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
            "modules": module_rows,
            "totals": {
                "module_count": len(module_rows),
                "total_hours": path.total_hours,
            },
        }

        self.ledger.append(
            "plan.generate",
            {
                "plan_id": plan_uid,
                "db_plan_id": db_plan_id,
                "profile_id": profile_id,
                "snapshot_id": snapshot_id,
                "module_count": len(module_rows),
                "total_hours": path.total_hours,
                "evidence_hash_count": len(evidence_sha256),
            },
        )

        return plan
