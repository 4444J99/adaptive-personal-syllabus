"""Domain models for adaptive personal syllabus."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DifficultyLevel(Enum):
    UNASSESSED = "unassessed"
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


@dataclass
class LearnerProfile:
    """A learner's interests and progress."""

    name: str
    organs_of_interest: list[str] = field(default_factory=list)  # e.g., ["I", "II", "V"]
    level: DifficultyLevel = DifficultyLevel.UNASSESSED
    completed_modules: list[str] = field(default_factory=list)

    total_modules: int = 0  # set after path generation for accurate progress

    @property
    def progress_pct(self) -> float:
        if not self.completed_modules:
            return 0.0
        if self.total_modules > 0:
            return min(100.0, len(self.completed_modules) / self.total_modules * 100.0)
        # Fallback when total is unknown: cap at 100%
        return min(100.0, len(self.completed_modules) * 10.0)


@dataclass
class LearningModule:
    """A single learning module in a syllabus path."""

    module_id: str
    title: str
    organ: str  # which organ this belongs to
    difficulty: DifficultyLevel
    readings: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    estimated_hours: float = 2.0
    prerequisites: list[str] = field(default_factory=list)  # module_ids


@dataclass
class LearningPath:
    """A personalized sequence of learning modules."""

    path_id: str
    title: str
    learner: LearnerProfile
    modules: list[LearningModule] = field(default_factory=list)

    @property
    def total_hours(self) -> float:
        return sum(m.estimated_hours for m in self.modules)

    @property
    def module_count(self) -> int:
        return len(self.modules)

    def next_module(self) -> LearningModule | None:
        for m in self.modules:
            if m.module_id not in self.learner.completed_modules:
                return m
        return None


@dataclass
class DocumentRecord:
    """Canonical document record persisted during corpus ingestion."""

    snapshot_id: int
    canonical_path: str
    rel_path: str
    sha256: str
    bytes: int
    lines: int
    mime: str
    family: str
    ingested_at: str


@dataclass
class DocumentChunk:
    """Heading-aware text chunk for retrieval and explainability."""

    document_id: int
    chunk_index: int
    heading_path: str
    text: str
    token_estimate: int


@dataclass
class LedgerEvent:
    """Append-only ledger event."""

    prev_hash: str
    event_hash: str
    event_type: str
    payload: dict[str, Any]
    created_at: str


@dataclass
class CorpusSnapshot:
    """Summary for a corpus ingestion snapshot."""

    snapshot_id: int
    snapshot_name: str
    root_path: str
    doc_count: int
    unique_payload_count: int
    created_at: str


@dataclass
class ChamberHookSpec:
    """Metadata for a chamber hook registration."""

    name: str
    description: str
    stage: str
    tags: list[str] = field(default_factory=list)


@dataclass
class CharacterNodeSpec:
    """Metadata for a character-node extension point."""

    name: str
    role: str
    focus_area: str


@dataclass
class PersonalizationRule:
    """Rule controlling profile-driven adaptation behavior."""

    rule_id: str
    description: str
    profile_fields: list[str] = field(default_factory=list)
    module_filters: list[str] = field(default_factory=list)
