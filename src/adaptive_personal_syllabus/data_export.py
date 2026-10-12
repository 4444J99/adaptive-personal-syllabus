"""Generate static data artifacts — sample learning paths.

Produces:
  data/sample-learning-paths.json — 3 sample paths (beginner/intermediate/advanced)

Uses the existing SyllabusGenerator with seed data (no database required).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .generator import SyllabusGenerator
from .models import DifficultyLevel, LearnerProfile

SEED_DIR = Path(__file__).parent.parent.parent.parent / "koinonia-db" / "seed"

SAMPLE_PROFILES = [
    LearnerProfile(
        name="Beginner Explorer",
        organs_of_interest=["I", "V"],
        level=DifficultyLevel.BEGINNER,
    ),
    LearnerProfile(
        name="Intermediate Practitioner",
        organs_of_interest=["II", "III"],
        level=DifficultyLevel.INTERMEDIATE,
    ),
    LearnerProfile(
        name="Advanced Architect",
        organs_of_interest=["I", "IV", "VI"],
        level=DifficultyLevel.ADVANCED,
    ),
]


def _path_to_dict(path: Any) -> dict[str, Any]:
    """Convert a LearningPath dataclass to a JSON-serializable dict."""
    return {
        "path_id": path.path_id,
        "title": path.title,
        "total_hours": path.total_hours,
        "module_count": path.module_count,
        "learner": {
            "name": path.learner.name,
            "organs_of_interest": path.learner.organs_of_interest,
            "level": path.learner.level.value,
        },
        "modules": [
            {
                "module_id": m.module_id,
                "title": m.title,
                "organ": m.organ,
                "difficulty": m.difficulty.value,
                "readings": m.readings,
                "questions": m.questions,
                "estimated_hours": m.estimated_hours,
            }
            for m in path.modules
        ],
    }


def generate_sample_paths(seed_dir: Path | None = None) -> list[dict[str, Any]]:
    """Generate sample learning paths for each difficulty level."""
    seed_dir = seed_dir or SEED_DIR
    generator = SyllabusGenerator(seed_dir=seed_dir)
    paths = []
    for profile in SAMPLE_PROFILES:
        path = generator.generate(profile)
        paths.append(_path_to_dict(path))
    return paths


def export_all(
    seed_dir: Path | None = None,
    output_dir: Path | None = None,
) -> list[Path]:
    """Generate all data artifacts and return output paths."""
    output_dir = output_dir or Path(__file__).parent.parent.parent / "data"
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []

    paths = generate_sample_paths(seed_dir)
    out_path = output_dir / "sample-learning-paths.json"
    out_path.write_text(json.dumps(paths, indent=2) + "\n")
    outputs.append(out_path)

    return outputs


def main() -> None:
    """CLI entry point for data export."""
    paths = export_all()
    for p in paths:
        print(f"Written: {p}")


if __name__ == "__main__":
    main()
