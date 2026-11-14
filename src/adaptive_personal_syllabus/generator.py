"""Generate personalized learning paths from organ system content."""
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from koinonia_db.constants import ORGAN_MAP

from .models import DifficultyLevel, LearnerProfile, LearningModule, LearningPath


class SyllabusGenerator:
    """Generates personalized learning paths based on organ interests and level."""

    def __init__(self, seed_dir: Path | None = None):
        self._seed_dir = seed_dir or Path(__file__).parent.parent.parent.parent / "koinonia-db" / "seed"
        self._taxonomy = self._load_taxonomy()
        self._readings = self._load_readings()

    def _load_taxonomy(self) -> dict:
        path = self._seed_dir / "taxonomy.json"
        if path.exists():
            return json.loads(path.read_text())
        return {"nodes": []}

    def _load_readings(self) -> dict:
        path = self._seed_dir / "reading_lists.json"
        if path.exists():
            return json.loads(path.read_text())
        return {"entries": []}

    def generate(self, profile: LearnerProfile) -> LearningPath:
        """Generate a personalized learning path for the given learner profile."""
        modules: list[LearningModule] = []

        for organ_code in profile.organs_of_interest:
            organ_slug = ORGAN_MAP.get(organ_code, organ_code.lower())
            organ_modules = self._build_modules_for_organ(organ_slug, profile.level)
            modules.extend(organ_modules)

        # Sort by difficulty (beginner first, then intermediate, then advanced)
        difficulty_order = {
            DifficultyLevel.BEGINNER: 0,
            DifficultyLevel.INTERMEDIATE: 1,
            DifficultyLevel.ADVANCED: 2,
        }
        modules.sort(key=lambda m: difficulty_order.get(m.difficulty, 1))

        # Update profile with total module count for accurate progress
        profile.total_modules = len(modules)

        # Filter out completed modules
        modules = [m for m in modules if m.module_id not in profile.completed_modules]

        return LearningPath(
            path_id=uuid4().hex[:8],
            title=f"Learning Path: {', '.join(profile.organs_of_interest)}",
            learner=profile,
            modules=modules,
        )

    def _build_modules_for_organ(
        self, organ_slug: str, level: DifficultyLevel
    ) -> list[LearningModule]:
        """Build learning modules from taxonomy and readings for a specific organ."""
        modules: list[LearningModule] = []

        # Find the organ node in taxonomy
        organ_node = None
        for node in self._taxonomy.get("nodes", []):
            if node["slug"] == organ_slug:
                organ_node = node
                break

        if not organ_node:
            return modules

        # Find readings matching this organ
        organ_readings = [
            e
            for e in self._readings.get("entries", [])
            if any(
                tag.startswith(organ_slug.split("-")[0] + "-") or tag == organ_slug
                for tag in e.get("organ_tags", [])
            )
        ]

        # Filter by difficulty
        level_value = level.value
        if level == DifficultyLevel.UNASSESSED:
            allowed = {"beginner", "intermediate", "advanced"}
        elif level == DifficultyLevel.BEGINNER:
            allowed = {"beginner", "intermediate"}
        elif level == DifficultyLevel.INTERMEDIATE:
            allowed = {"intermediate", "advanced"}
        else:
            allowed = {"advanced"}

        filtered_readings = [
            r for r in organ_readings if r.get("difficulty", "intermediate") in allowed
        ]

        # Create a module for each child topic
        for child in organ_node.get("children", []):
            # Filter readings matching this specific child topic
            child_slug = child["slug"]
            child_readings = [
                r["title"]
                for r in filtered_readings
                if any(
                    tag == child_slug or child_slug in tag
                    for tag in r.get("organ_tags", [])
                )
            ][:3]  # max 3 readings per module
            if not child_readings:
                # Fall back to organ-level readings if none match the child
                child_readings = [r["title"] for r in filtered_readings][:3]
            if not child_readings:
                child_readings = [f"See {organ_node['label']} documentation"]

            modules.append(
                LearningModule(
                    module_id=f"{child['slug']}-{level_value[:3]}",
                    title=child["label"],
                    organ=organ_slug,
                    difficulty=level,
                    readings=child_readings,
                    questions=[
                        f"What is the core idea behind {child['label']}?",
                        f"How does {child['label']} connect to {organ_node['label']}?",
                        f"What would you build or explore using {child['label']}?",
                    ],
                    estimated_hours=2.0 if level != DifficultyLevel.ADVANCED else 3.0,
                    prerequisites=list(child.get("prerequisites", [])),
                )
            )

        return modules
