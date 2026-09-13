"""Database-backed syllabus generator — reads taxonomy/readings from Neon and persists paths."""

from __future__ import annotations

from uuid import uuid4

from koinonia_db.models.reading import Entry
from koinonia_db.models.salon import TaxonomyNodeRow
from koinonia_db.models.syllabus import LearnerProfileRow, LearningModuleRow, LearningPathRow
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from .models import DifficultyLevel, LearnerProfile, LearningModule, LearningPath


class DatabaseSyllabusGenerator:
    """Generate and persist learning paths using the koinonia-db database."""

    def __init__(self, database_url: str) -> None:
        url = database_url
        if "+psycopg" not in url and url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        self._engine = create_engine(url)

    def generate(self, profile: LearnerProfile) -> LearningPath:
        """Generate a path from DB data and persist it."""
        with Session(self._engine) as session:
            taxonomy = self._load_taxonomy(session)
            readings = self._load_readings(session)
            modules = self._build_modules(profile, taxonomy, readings)

            path = LearningPath(
                path_id=uuid4().hex[:8],
                title=f"Learning Path: {', '.join(profile.organs_of_interest)}",
                learner=profile,
                modules=modules,
            )

            self._persist(session, profile, path)
            return path

    def _load_taxonomy(self, session: Session) -> list[dict]:
        """Load taxonomy as nested dicts from the database."""
        roots = session.scalars(
            select(TaxonomyNodeRow).where(TaxonomyNodeRow.parent_id.is_(None))
        ).all()
        result = []
        for root in roots:
            children = session.scalars(
                select(TaxonomyNodeRow).where(TaxonomyNodeRow.parent_id == root.id)
            ).all()
            result.append({
                "slug": root.slug,
                "label": root.label,
                "organ_id": root.organ_id,
                "description": root.description,
                "children": [
                    {"slug": c.slug, "label": c.label, "description": c.description}
                    for c in children
                ],
            })
        return result

    def _load_readings(self, session: Session) -> list[dict]:
        """Load reading entries as dicts from the database."""
        entries = session.scalars(select(Entry)).all()
        return [
            {
                "title": e.title,
                "author": e.author,
                "organ_tags": e.organ_tags or [],
                "difficulty": e.difficulty,
                "source_type": e.source_type,
            }
            for e in entries
        ]

    def _build_modules(
        self,
        profile: LearnerProfile,
        taxonomy: list[dict],
        readings: list[dict],
    ) -> list[LearningModule]:
        """Build learning modules from DB-loaded taxonomy and readings."""
        from .generator import ORGAN_MAP

        modules = []
        for organ_code in profile.organs_of_interest:
            organ_slug = ORGAN_MAP.get(organ_code, organ_code.lower())
            organ_node = next(
                (n for n in taxonomy if n["slug"] == organ_slug), None
            )
            if not organ_node:
                continue

            organ_readings = [
                e for e in readings
                if any(
                    tag.startswith(organ_slug.split("-")[0] + "-") or tag == organ_slug
                    for tag in e.get("organ_tags", [])
                )
            ]

            level = profile.level
            if level == DifficultyLevel.BEGINNER:
                allowed = {"beginner", "intermediate"}
            elif level == DifficultyLevel.INTERMEDIATE:
                allowed = {"intermediate", "advanced"}
            else:
                allowed = {"advanced"}

            filtered = [r for r in organ_readings if r.get("difficulty", "intermediate") in allowed]

            for child in organ_node.get("children", []):
                child_readings = [r["title"] for r in filtered][:3]
                if not child_readings:
                    child_readings = [f"See {organ_node['label']} documentation"]

                modules.append(
                    LearningModule(
                        module_id=f"{child['slug']}-{level.value[:3]}",
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
                    )
                )

        difficulty_order = {
            DifficultyLevel.BEGINNER: 0,
            DifficultyLevel.INTERMEDIATE: 1,
            DifficultyLevel.ADVANCED: 2,
        }
        modules.sort(key=lambda m: difficulty_order.get(m.difficulty, 1))
        return modules

    def _persist(self, session: Session, profile: LearnerProfile, path: LearningPath) -> None:
        """Save the generated path to the syllabus schema."""
        learner_row = LearnerProfileRow(
            name=profile.name,
            organs_of_interest=profile.organs_of_interest,
            level=profile.level.value,
            completed_modules=profile.completed_modules,
        )
        session.add(learner_row)
        session.flush()

        path_row = LearningPathRow(
            path_id=path.path_id,
            title=path.title,
            learner_id=learner_row.id,
            total_hours=path.total_hours,
        )
        session.add(path_row)
        session.flush()

        for i, mod in enumerate(path.modules):
            session.add(LearningModuleRow(
                path_id=path_row.id,
                module_id=mod.module_id,
                title=mod.title,
                organ=mod.organ,
                difficulty=mod.difficulty.value,
                readings=mod.readings,
                questions=mod.questions,
                estimated_hours=mod.estimated_hours,
                seq=i,
            ))

        session.commit()
