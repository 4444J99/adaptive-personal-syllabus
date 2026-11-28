"""Domain-slice registry (#59, MTR-028).

A slice is one bounded learning module outside the organ taxonomy: one
module, one source, one encounter. Slices live in ``data/slices/*.json``
(one file per slice; the registry is the set of files, not a central
index) and are merged into :meth:`Planner.generate` only when the
learner's profile asks for the slice's domain — the organ generator
never sees them, and a profile that never names the domain never gets
the module.

Why a registry instead of seed taxonomy: modules come from the
koinonia-db seed (``SyllabusGenerator``), which carries the eight-organ
taxonomy; world studies is not an organ, so the slice cannot be a seed
node. The registry keeps the slice definition next to its source file
and its evaluation rule, in one reviewable place, instead of hiding a
domain inside the generator.

The module shape is the planner's own: a :class:`LearningModule`
(module_id, title, organ, difficulty, readings, questions,
estimated_hours, prerequisites). The criterion
(``explain_with_counterexample``) is not a module field — it lives in
the encounter's prior-task-evidence matching (``encounter.py``), so the
registry records it under ``evaluation`` and the tests assert the
encounter routes on it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import DifficultyLevel, LearningModule

REGISTRY_DIR = Path(__file__).resolve().parents[2] / "data" / "slices"

# Required fields per slice entry. A missing field is a registry error,
# not a silent skip: a half-defined slice must fail loudly at load time
# rather than vanish from a plan.
_SLICE_FIELDS = ("slice_id", "domain", "module", "source", "evaluation")
_MODULE_FIELDS = (
    "module_id",
    "title",
    "organ",
    "difficulty",
    "readings",
    "questions",
    "estimated_hours",
    "prerequisites",
)
_SOURCE_FIELDS = (
    "title",
    "author",
    "translator",
    "edition",
    "url",
    "retrieved",
    "license",
    "file",
    "excerpt",
    "sha256",
)


def _require(mapping: dict[str, Any], field: str, where: str) -> Any:
    value = mapping.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"Slice registry {where} requires non-empty {field!r}")
    return value


def load_slices(directory: Path | str = REGISTRY_DIR) -> list[dict[str, Any]]:
    """Load and validate every slice file in the registry directory.

    Why validation here: the registry is load-bearing plan content — a
    malformed slice that silently dropped out of a plan would read as
    "no slice exists", the exact failure step 1 of #59 reproduces. An
    absent directory means no slices are registered (the pre-#59 state),
    not an error; a present-but-malformed file is.
    """
    directory = Path(directory)
    if not directory.is_dir():
        return []
    slices: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or not isinstance(raw.get("slices"), list):
            raise TypeError(f"Slice registry {path} must hold a 'slices' list")
        for entry in raw["slices"]:
            if not isinstance(entry, dict):
                raise TypeError(f"Slice registry {path} holds a non-object entry")
            for field in _SLICE_FIELDS:
                _require(entry, field, f"{path.name}:{entry.get('slice_id', '?')}")
            module = entry["module"]
            if not isinstance(module, dict):
                raise TypeError(f"Slice {entry['slice_id']} module must be an object")
            for field in _MODULE_FIELDS:
                _require(module, field, f"slice {entry['slice_id']} module")
            source = entry["source"]
            if not isinstance(source, dict):
                raise TypeError(f"Slice {entry['slice_id']} source must be an object")
            for field in _SOURCE_FIELDS:
                _require(source, field, f"slice {entry['slice_id']} source")
            sha = str(source["sha256"])
            if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha.lower()):
                raise ValueError(
                    f"Slice {entry['slice_id']} source sha256 must be 64 hex characters"
                )
            evaluation = entry["evaluation"]
            if not isinstance(evaluation, dict):
                raise TypeError(f"Slice {entry['slice_id']} evaluation must be an object")
            _require(evaluation, "criterion", f"slice {entry['slice_id']} evaluation")
            slices.append(entry)
    return slices


def slice_modules_for(
    domains: list[str], directory: Path | str = REGISTRY_DIR
) -> list[LearningModule]:
    """The slice modules for the requested domains, in registry order.

    A domain matches when it equals a slice's ``domain`` exactly; the
    caller maps organ codes to slugs the same way the generator does
    (``ORGAN_MAP`` with a lowercase fallback), so ``world-studies`` in a
    profile reaches the ``world-studies`` slice. Unknown domains yield
    no modules — a slice is opt-in by naming its domain, never default.
    """
    wanted = {str(d).strip().lower() for d in domains if str(d).strip()}
    modules: list[LearningModule] = []
    for entry in load_slices(directory):
        if str(entry["domain"]).strip().lower() not in wanted:
            continue
        module = entry["module"]
        modules.append(
            LearningModule(
                module_id=str(module["module_id"]),
                title=str(module["title"]),
                organ=str(module["organ"]),
                difficulty=DifficultyLevel(str(module["difficulty"])),
                readings=[str(r) for r in module["readings"]],
                questions=[str(q) for q in module["questions"]],
                estimated_hours=float(module["estimated_hours"]),
                prerequisites=[str(p) for p in module["prerequisites"]],
            )
        )
    return modules
