"""Source admission (#48, MTR-017).

Admission answers "may this source be used" as a recorded, attributed
decision — never inferred from retrieval. It is separate from two things
it is often confused with:

- *Containment* (`corpus.discover_documents`): whether a file may be read
  at all. Containment + the privacy inventory (#33/#34) decide what
  enters a snapshot; admission decides what the planner and the support
  path may draw on.
- *Freshness* (`freshness.py`): what the last refresh observed about a
  source. Refresh is observation; admission is a decision. A refresh
  re-reads a source whether or not it is admitted — otherwise no
  evidence could ever be gathered about an unadmitted source — except a
  source whose latest admission decision is ``revoked``: its bytes are
  never re-read, the same as an inventory-refused source.

Keying. An admission binds to exact bytes of one source identity:
``(root_path, rel_path, sha256)``, resolved through #54's
``source_records``. It is NOT keyed by ``document_id``: a document id is
snapshot-scoped, so a re-ingest of identical bytes would silently drop
every admission. A changed file (sha drift) has no admission for its new
bytes and is unadmitted until re-admitted. The granting ``document_id``
is stored for traceability only.

Decisions. ``admitted`` / ``rejected`` / ``revoked``; no row means
``unadmitted``. The latest row wins: a later admit re-admits a revoked
source, a later revoke supersedes an admit. ``content_kind`` is a
persisted fact about the document, not a decision: ``passage`` (decoded
text exists), ``metadata_only`` (binary intake, no extraction, no
chunks), ``extraction_failed`` (a text file that could not be decoded or
validated). The planner requires decision ``admitted`` AND kind
``passage``; an admitted ``metadata_only`` document is usable as
metadata, never as passage support. Admission never promotes a
candidate to support — only a human judgment does (#50).

Access. ``public`` / ``restricted`` / ``private``. A ``private`` access
decision redacts the source from every output surface: its rel_path is
never emitted by ``corpus stats`` / plan output, and ``corpus passage``
and ``corpus support`` refuse it outright (no paths, no contents).
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .storage import Storage

ACCESS_VALUES = ("public", "restricted", "private")
DECISION_VALUES = ("admitted", "rejected", "revoked")
CONTENT_KINDS = ("passage", "metadata_only", "extraction_failed")

UNADMITTED = "unadmitted"

# A document whose bytes were never decoded carries no usable passage.
# Kept small and explicit on purpose: this is a tripwire, not a license
# parser. A restrictive claim embedded in the text contradicting a
# permissive declared license (or the reverse) refuses admission — the
# operator corrects the declared record instead of overriding the tripwire.
RESTRICTIVE_MARKERS = (
    "all rights reserved",
    "do not distribute",
    "do not copy",
    "confidential",
    "proprietary",
    "internal use only",
)
PERMISSIVE_MARKERS = (
    "public domain",
    "cc0",
    "cc-by",
    "cc by",
    "mit license",
    "apache license",
    "bsd license",
    "gpl",
    "creative commons",
)


def compute_content_kind(text: str | None, *, extraction_failed: bool = False) -> str:
    """The persisted kind of one ingested document.

    Decoded text exists → ``passage`` (even with zero chunks: an empty
    text file is a passage document with no passages, not a metadata
    record). Binary intake (no decoded text) → ``metadata_only``.
    ``extraction_failed`` is classified here for a decode/validation
    failure; ingest keeps its fail-fast contract, so CLI ingest never
    produces one today — the kind exists so a non-fatal extraction path
    can record it instead of silently dropping the document.
    """
    if extraction_failed:
        return "extraction_failed"
    return "passage" if text is not None else "metadata_only"


def _license_class(value: str) -> str:
    lowered = value.lower()
    if any(marker in lowered for marker in RESTRICTIVE_MARKERS):
        return "restrictive"
    if any(marker in lowered for marker in PERMISSIVE_MARKERS):
        return "permissive"
    return "unknown"


def find_license_contradiction(
    *, declared_license: str, embedded_text: str | None
) -> str | None:
    """A contradiction between the declared license and the document text.

    Returns a human-readable description, or None when there is nothing
    to contradict (no embedded text, or no classifiable claim on either
    side). A contradiction refuses admission — never silently admitted.
    """
    if embedded_text is None:
        return None
    declared = _license_class(declared_license)
    if declared == "unknown":
        return None
    embedded = _license_class(embedded_text)
    if embedded == "unknown" or embedded == declared:
        return None
    return (
        f"license contradiction: embedded text claims {embedded} use "
        f"while the declared license ({declared_license!r}) claims {declared} use"
    )


def _require_str(record: dict[str, Any], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Admission requires {key} (non-empty string)")
    return value.strip()


def _require_sha(record: dict[str, Any], key: str = "sha256") -> str:
    value = record.get(key)
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value.lower())
    ):
        raise ValueError(f"Admission requires {key} (64 hex characters)")
    return value.lower()


def _parse_reviewed_at(record: dict[str, Any]) -> str:
    value = record.get("reviewed_at")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Admission requires reviewed_at (ISO date or datetime)")
    try:
        datetime.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError("reviewed_at must be a valid ISO date or datetime") from exc
    return value.strip()


def _resolve_document(
    storage: Storage, record: dict[str, Any], *, conn: sqlite3.Connection | None = None
) -> dict[str, Any]:
    document_id = record.get("document_id")
    if type(document_id) is not int or document_id <= 0:
        raise ValueError("document_id must be a positive integer")
    doc = storage.get_document(document_id, conn=conn)
    if doc is None:
        raise ValueError(f"No document with id {document_id}")
    sha256 = _require_sha(record)
    if str(doc["sha256"]) != sha256:
        raise ValueError(
            "sha256 mismatch: admission binds to the exact bytes of the "
            "current document row; re-ingest or re-admit, never carry over"
        )
    return doc


def validate_admission_record(
    storage: Storage, record: dict[str, Any], *, conn: sqlite3.Connection | None = None
) -> dict[str, Any]:
    """Validate an admit record and return the normalized row to persist.

    Mirrors `support.validate_judgment`'s attributed pattern: the record
    is a declared decision, never inferred from retrieval. The embedded
    license-contradiction tripwire refuses a record whose declared license
    contradicts the document's own text.
    """
    if not isinstance(record, dict):
        raise ValueError("Admission record must be an object")  # noqa: TRY004
    doc = _resolve_document(storage, record, conn=conn)
    owner = _require_str(record, "owner")
    license_value = _require_str(record, "license")
    access = _require_str(record, "access")
    if access not in ACCESS_VALUES:
        raise ValueError(f"access must be one of {', '.join(ACCESS_VALUES)}")
    provenance = _require_str(record, "provenance")
    admitted_by = _require_str(record, "admitted_by")
    admission_basis = _require_str(record, "admission_basis")
    reviewer = _require_str(record, "reviewer")
    reviewed_at = _parse_reviewed_at(record)
    contradiction = find_license_contradiction(
        declared_license=license_value,
        embedded_text=_document_text(storage, doc, conn=conn),
    )
    if contradiction is not None:
        raise ValueError(contradiction)
    return {
        "root_path": str(doc["root_path"]),
        "rel_path": str(doc["rel_path"]),
        "sha256": str(doc["sha256"]),
        "document_id": int(doc["id"]),
        "decision": "admitted",
        "owner": owner,
        "license": license_value,
        "access": access,
        "provenance": provenance,
        "admitted_by": admitted_by,
        "admission_basis": admission_basis,
        "reviewer": reviewer,
        "reviewed_at": reviewed_at,
        "admitted_at": datetime.now(tz=UTC).replace(microsecond=0).isoformat(),
        "revoked_by": None,
        "revocation_reason": None,
        "revoked_at": None,
    }


def validate_revocation_record(
    storage: Storage, record: dict[str, Any], *, conn: sqlite3.Connection | None = None
) -> dict[str, Any]:
    """Validate a revoke record and return the normalized row to persist.

    Revocation needs no prior admission: the decision is the latest row
    for the source, and a later admit re-admits it. The sha must still
    match the current document row — revoking bytes that are no longer
    current revokes nothing.
    """
    if not isinstance(record, dict):
        raise ValueError("Revocation record must be an object")  # noqa: TRY004
    doc = _resolve_document(storage, record, conn=conn)
    revoked_by = _require_str(record, "revoked_by")
    revocation_reason = _require_str(record, "revocation_reason")
    reviewed_at = record.get("reviewed_at")
    if reviewed_at is not None:
        reviewed_at = _parse_reviewed_at(record)
    return {
        "root_path": str(doc["root_path"]),
        "rel_path": str(doc["rel_path"]),
        "sha256": str(doc["sha256"]),
        "document_id": int(doc["id"]),
        "decision": "revoked",
        "owner": None,
        "license": None,
        "access": None,
        "provenance": None,
        "admitted_by": None,
        "admission_basis": None,
        "reviewer": None,
        "reviewed_at": reviewed_at,
        "admitted_at": None,
        "revoked_by": revoked_by,
        "revocation_reason": revocation_reason,
        "revoked_at": datetime.now(tz=UTC).replace(microsecond=0).isoformat(),
    }


def _document_text(
    storage: Storage, doc: dict[str, Any], *, conn: sqlite3.Connection | None = None
) -> str | None:
    """The decoded text of one document, or None for a metadata-only one."""
    chunks = storage.list_document_chunks(snapshot_id=int(doc["snapshot_id"]))
    texts = [str(c["text"]) for c in chunks if int(c["document_id"]) == int(doc["id"])]
    if not texts:
        return None
    return "\n".join(texts)


def latest_admission_for_source(
    storage: Storage,
    *,
    root_path: str,
    rel_path: str,
    sha256: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any] | None:
    """The latest admission decision for one source identity.

    With ``sha256`` given, only a decision bound to those exact bytes
    counts — a sha drift leaves the source unadmitted. Without it, the
    latest decision for the source regardless of bytes (used by refresh
    to decide whether re-reading is even allowed: a revoked source's
    bytes are never re-read).
    """
    return storage.latest_source_admission(
        root_path, rel_path, sha256=sha256, conn=conn
    )


def admission_for_document(
    storage: Storage, document_id: int, *, conn: sqlite3.Connection | None = None
) -> dict[str, Any]:
    """The admission state of one document row: status, kind, decision.

    ``status`` is ``admitted`` only when the latest decision bound to
    this document's exact bytes is ``admitted``; otherwise it is the
    decision (``rejected`` / ``revoked``) or ``unadmitted`` when no row
    exists. ``access`` is the decision's access class, or None when
    unadmitted.
    """
    doc = storage.get_document(document_id, conn=conn)
    if doc is None:
        raise ValueError(f"No document with id {document_id}")
    row = latest_admission_for_source(
        storage,
        root_path=str(doc["root_path"]),
        rel_path=str(doc["rel_path"]),
        sha256=str(doc["sha256"]),
        conn=conn,
    )
    decision = str(row["decision"]) if row is not None else UNADMITTED
    return {
        "document_id": int(doc["id"]),
        "status": decision,
        "decision": decision,
        "access": str(row["access"]) if row is not None and row.get("access") else None,
        "content_kind": str(doc.get("content_kind") or "passage"),
        "admission": row,
    }


def redact_rel_path(rel_path: str, access: str | None) -> str:
    """A private source's path never appears in output; anything else does."""
    return "[redacted: private]" if access == "private" else rel_path
