"""Shared admission fixture helpers (#48, MTR-017).

Kept out of `test_source_admission.py` so other suites can admit
fixtures without importing the test module itself (which imports
`tests.test_planner` — the reverse import would be circular).
"""

from __future__ import annotations

from typing import Any

from adaptive_personal_syllabus.admission import validate_admission_record
from adaptive_personal_syllabus.storage import Storage


def admit_record(doc: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    """A valid admit record for one document row."""
    record = {
        "document_id": int(doc["id"]),
        "sha256": str(doc["sha256"]),
        "owner": "synthetic-owner",
        "license": "CC-BY-4.0",
        "access": "public",
        "provenance": "synthetic fixture",
        "admitted_by": "synthetic-operator",
        "admission_basis": "synthetic fixture review",
        "reviewer": "synthetic-reviewer",
        "reviewed_at": "2026-11-22",
    }
    record.update(overrides)
    return record


def admit_document(storage: Storage, doc: dict[str, Any], **overrides: Any) -> int:
    """Admit one document row through the validated record path."""
    normalized = validate_admission_record(storage, admit_record(doc, **overrides))
    return storage.record_source_admission(normalized)


def admit_all_documents(storage: Storage, snapshot_id: int, **overrides: Any) -> list[int]:
    """Admit every document in a snapshot (fixture helper for other suites)."""
    return [
        admit_document(storage, doc, **overrides)
        for doc in storage.list_documents(snapshot_id=snapshot_id)
    ]
