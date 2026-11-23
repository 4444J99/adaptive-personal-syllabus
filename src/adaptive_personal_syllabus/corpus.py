"""Corpus ingestion and document chunking utilities."""
from __future__ import annotations

import csv
import errno
import fnmatch
import hashlib
import json
import mimetypes
import os
import re
import stat
import tomllib
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

import yaml

from .admission import compute_content_kind
from .ledger import Ledger
from .models import CorpusSnapshot
from .storage import DEFAULT_MAX_AGE_HOURS, REFRESH_CONTENT_OUTCOMES, Storage, utcnow_iso


class RateLimitError(Exception):
    """A source read refused by the source's rate limiter.

    The local-filesystem adapter never raises this — a local read has no
    rate limiter — but a remote source adapter (a later build, not this one)
    raises it, and `CorpusRefresher` maps it to the `rate_limited` outcome.
    Tests raise it by monkeypatching the read path.
    """

SUPPORTED_EXTENSIONS = {
    ".md",
    ".txt",
    ".yaml",
    ".yml",
    ".json",
    ".toml",
    ".csv",
    ".tsv",
    ".rst",
    ".pdf",
    ".docx",
}

TEXT_EXTENSIONS = {
    ".md",
    ".txt",
    ".yaml",
    ".yml",
    ".json",
    ".toml",
    ".csv",
    ".tsv",
    ".rst",
}

SKIP_DIRECTORIES = {
    ".git", ".venv", ".pytest_cache", "__pycache__", ".mypy_cache",
    ".private", ".secrets", ".adaptive-syllabus",
}


FAMILY_BY_EXTENSION = {
    ".md": "markdown",
    ".txt": "text",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".csv": "tabular",
    ".tsv": "tabular",
    ".rst": "text",
    ".pdf": "binary",
    ".docx": "binary",
}


@dataclass(frozen=True)
class CandidateDocument:
    path: Path
    rel_path: str
    extension: str
    sha256: str
    size_bytes: int
    lines: int
    mime: str
    family: str
    text: str | None


def _should_skip(path: Path, root: Path) -> bool:
    rel_parts = path.relative_to(root).parts
    return any(part in SKIP_DIRECTORIES for part in rel_parts)


# Classification-aware admission (#34, MTR-007 step 2). The #33 inventory
# (docs/privacy-classification.yaml, ADR 003) classifies paths; a root that
# carries one refuses `private-never-in-git` paths at discovery. A repo root
# carries it at docs/privacy-classification.yaml; a docs root (the audit
# gate's `--root ./docs`) carries it at privacy-classification.yaml.
PRIVACY_INVENTORY_RELPATHS = (
    "docs/privacy-classification.yaml",
    "privacy-classification.yaml",
)
PRIVATE_CLASS = "private-never-in-git"


def _inventory_match(pattern: str, path: str) -> bool:
    """Match one inventory pattern against a root-relative path.

    `*` matches within one path segment; `**` matches zero or more segments.
    Same semantics as tests/test_privacy_classification.py::inventory_match;
    the classification guard pins the inventory, this pins admission.
    """

    def match_parts(pattern_parts: list[str], parts: list[str]) -> bool:
        if not pattern_parts:
            return not parts
        head, rest = pattern_parts[0], pattern_parts[1:]
        if head == "**":
            return any(match_parts(rest, parts[i:]) for i in range(len(parts) + 1))
        if not parts:
            return False
        return fnmatch.fnmatchcase(parts[0], head) and match_parts(rest, parts[1:])

    return match_parts(pattern.split("/"), path.split("/"))


def _load_privacy_inventory(root: Path) -> dict | None:
    """Load the classification inventory for this tree, if one is present.

    The inventory is read through the admitted-bytes path so a symlinked
    inventory is refused like any other symlink escape. A malformed inventory
    fails closed: silently admitting private-classified paths would be worse
    than a loud ingest failure the guard test catches in CI.
    """
    for rel in PRIVACY_INVENTORY_RELPATHS:
        candidate = root / rel
        if candidate.is_file() and not candidate.is_symlink():
            data = yaml.safe_load(_read_admitted_bytes(root, candidate).decode("utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
                raise ValueError("ERR_PRIVACY_INVENTORY: classification inventory is malformed")
            return data
    return None


def _is_private_classified(inventory: dict, rel_path: str) -> bool:
    """True when a `private-never-in-git` inventory entry matches the path.

    Private wins on conflict: the guard test enforces exactly one entry per
    tracked path, but an untracked file can match a public pattern and a
    private one (e.g. `docs-audit-ci.md` matches `*.md` and `docs-audit-ci.*`).
    Refusal is the fail-closed side. `review` stays admitted per ADR 003.
    """
    for entry in inventory.get("entries") or []:
        if not isinstance(entry, dict) or entry.get("class") != PRIVATE_CLASS:
            continue
        patterns = entry.get("patterns") or []
        if any(_inventory_match(str(pattern), rel_path) for pattern in patterns):
            return True
    return False


def discover_documents(
    root: Path,
    exclude_paths: set[Path] | None = None,
    *,
    apply_inventory: bool = True,
) -> list[Path]:
    """Discover regular files; symlink aliases are not admitted sources.

    With `apply_inventory` (the default), the privacy-classification
    inventory refuses `private-never-in-git` paths: that is admission
    (#33/#34). With it off, every present file is listed: the refresher
    uses that to tell `revoked` (present but no longer admitted) apart
    from `deleted` (absent from the root entirely).
    """
    root = root.expanduser().resolve(strict=True)
    excluded = {p.expanduser().resolve() for p in (exclude_paths or set())}
    inventory = _load_privacy_inventory(root) if apply_inventory else None

    def allowed(path: Path) -> bool:
        if path.is_symlink() or _should_skip(path, root):
            return False
        if inventory is not None and _is_private_classified(
            inventory, str(path.relative_to(root))
        ):
            return False
        resolved = path.resolve()
        return resolved.is_relative_to(root) and not any(
            resolved == item or item in resolved.parents for item in excluded
        )

    files: list[Path] = []
    for parent, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(name for name in dirs if allowed(Path(parent) / name))
        for name in names:
            path = Path(parent) / name
            if path.suffix.lower() in SUPPORTED_EXTENSIONS and allowed(path) and path.is_file():
                files.append(path)
    return sorted(files, key=lambda p: str(p.relative_to(root)))


def _read_admitted_bytes(root: Path, path: Path) -> bytes:
    """Open every component relative to a directory fd, refusing symlink races.

    The input root is trusted and explicitly chosen. This is containment, not
    content classification or protection against a hostile filesystem owner.
    """
    try:
        relative = path.relative_to(root)
        if not relative.parts or ".." in relative.parts or _should_skip(path, root):
            raise ValueError("ERR_SOURCE_BOUNDARY: source is outside admission policy")
        if not hasattr(os, "O_NOFOLLOW") or os.open not in os.supports_dir_fd:
            raise ValueError("ERR_SOURCE_BOUNDARY: secure source opening is unsupported")
        with ExitStack() as cleanup:
            directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            cleanup.callback(os.close, directory)
            for part in relative.parts[:-1]:
                directory = os.open(
                    part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
                )
                cleanup.callback(os.close, directory)
            source = os.open(
                relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
            )
            cleanup.callback(os.close, source)
            if not stat.S_ISREG(os.fstat(source).st_mode):
                raise ValueError("ERR_SOURCE_BOUNDARY: source must be a regular file")
            chunks = []
            while chunk := os.read(source, 1024 * 1024):
                chunks.append(chunk)
            return b"".join(chunks)
    except TimeoutError:
        # A read that timed out is a refresh outcome, not a boundary error:
        # let it reach the refresher, which records `timeout` and continues.
        raise
    except OSError as exc:
        # Do not echo symlink targets or private filesystem paths.
        raise ValueError("ERR_SOURCE_BOUNDARY: source could not be admitted safely") from exc


def _decode_text(data: bytes, path: Path) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"ERR_ENCODING_UNSUPPORTED: Unsupported encoding for {path}. Expected UTF-8.") from exc


def _validate_content(ext: str, text: str, path: Path) -> None:
    if ext == ".json":
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"ERR_MALFORMED_JSON: Malformed JSON file: {path}") from exc
    elif ext in {".yaml", ".yml"}:
        try:
            yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ValueError(f"ERR_MALFORMED_YAML: Malformed YAML file: {path}") from exc
    elif ext == ".toml":
        try:
            tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise ValueError(f"ERR_MALFORMED_TOML: Malformed TOML file: {path}") from exc
    elif ext in {".csv", ".tsv"}:
        delimiter = "," if ext == ".csv" else "\t"
        reader = csv.reader(text.splitlines(), delimiter=delimiter)
        # Consume all rows to fail-fast on malformed delimiters/quoting.
        for _ in reader:
            pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _family(ext: str) -> str:
    return FAMILY_BY_EXTENSION.get(ext, "unknown")


def _mime(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def _count_lines(text: str | None, data: bytes) -> int:
    if text is None:
        if not data:
            return 0
        return data.count(b"\n") + 1
    if not text:
        return 0
    return text.count("\n") + 1


def _is_heading_line(line: str) -> tuple[int, str] | None:
    markdown_match = re.match(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$", line)
    if markdown_match:
        level = len(markdown_match.group(1))
        heading = markdown_match.group(2).strip()
        return level, heading
    return None


def heading_aware_chunks(text: str) -> list[tuple[str, str]]:
    """Split text into heading-aware chunks with heading path labels."""
    if not text.strip():
        return []

    chunks: list[tuple[str, str]] = []
    heading_stack: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        chunk_text = "\n".join(buffer).strip()
        if chunk_text:
            heading_path = " / ".join(heading_stack)
            chunks.append((heading_path, chunk_text))
        buffer.clear()

    for line in text.splitlines():
        heading = _is_heading_line(line)
        if heading:
            flush()
            level, title = heading
            heading_stack[:] = heading_stack[: level - 1]
            heading_stack.append(title)
            continue
        buffer.append(line)

    flush()

    if not chunks:
        chunks.append(("", text.strip()))

    return chunks


def build_candidate(root: Path, path: Path) -> CandidateDocument:
    """Read one admitted file into a candidate (shared by ingest + refresh)."""
    data = _read_admitted_bytes(root, path)
    ext = path.suffix.lower()
    text = None
    if ext in TEXT_EXTENSIONS:
        text = _decode_text(data, path)
        _validate_content(ext, text, path)

    rel_path = str(path.relative_to(root))
    return CandidateDocument(
        path=path,
        rel_path=rel_path,
        extension=ext,
        sha256=_sha256(data),
        size_bytes=len(data),
        lines=_count_lines(text, data),
        mime=_mime(path),
        family=_family(ext),
        text=text,
    )


class CorpusIngestor:
    """Ingest repository corpus, deduplicate by content hash, and persist chunks."""

    def __init__(self, storage: Storage, ledger: Ledger | None = None) -> None:
        self.storage = storage
        self.ledger = ledger

    def _build_candidate(self, root: Path, path: Path) -> CandidateDocument:
        return build_candidate(root, path)

    def ingest(
        self,
        root: Path,
        snapshot_name: str,
        exclude_paths: set[Path] | None = None,
    ) -> CorpusSnapshot:
        root = root.expanduser().resolve()
        if not root.exists() or not root.is_dir():
            raise ValueError(f"Invalid root directory: {root}")

        paths = discover_documents(root, exclude_paths=exclude_paths)
        candidates = [self._build_candidate(root, p) for p in paths]

        by_hash: dict[str, list[CandidateDocument]] = {}
        for c in candidates:
            by_hash.setdefault(c.sha256, []).append(c)

        canonical_docs = 0
        alias_count = 0
        chunk_count = 0
        ingested_at = utcnow_iso()
        with self.storage.connection() as conn:
            snapshot_id = self.storage.insert_snapshot(
                snapshot_name=snapshot_name,
                root_path=str(root),
                doc_count=len(candidates),
                unique_payload_count=len(by_hash),
                conn=conn,
            )

            for sha in sorted(by_hash):
                # Prefer a decoded representation of identical bytes. A binary-labelled
                # alias sorting first must not discard text that was actually recovered.
                # Paths remain aliases; content equality does not establish an edition.
                group = sorted(by_hash[sha], key=lambda c: (c.text is None, c.rel_path))
                canonical = group[0]
                canonical_docs += 1
                doc_id = self.storage.insert_document(
                    snapshot_id=snapshot_id,
                    canonical_path=str(canonical.path),
                    rel_path=canonical.rel_path,
                    sha256=canonical.sha256,
                    size_bytes=canonical.size_bytes,
                    lines=canonical.lines,
                    mime=canonical.mime,
                    family=canonical.family,
                    # Source admission (#48 step 3): the kind is a
                    # persisted fact about the content — decoded text
                    # exists (`passage`) or the intake is metadata-only.
                    content_kind=compute_content_kind(canonical.text),
                    ingested_at=ingested_at,
                    conn=conn,
                )

                if canonical.text is not None:
                    chunks_to_insert: list[tuple[int, str, str, int]] = []
                    for idx, (heading_path, chunk_text) in enumerate(
                        heading_aware_chunks(canonical.text)
                    ):
                        token_estimate = len(chunk_text.split())
                        chunks_to_insert.append((idx, heading_path, chunk_text, token_estimate))
                    chunk_count += self.storage.insert_chunks(
                        document_id=doc_id,
                        chunks=chunks_to_insert,
                        conn=conn,
                    )

                alias_paths = [str(alias.path) for alias in group[1:]]
                alias_count += self.storage.insert_aliases(
                    document_id=doc_id,
                    alias_paths=alias_paths,
                    conn=conn,
                )

            if self.ledger is not None:
                self.ledger.append(
                    "corpus.ingest",
                    {
                        "snapshot_id": snapshot_id,
                        "snapshot_name": snapshot_name,
                        "root_path": str(root),
                        "doc_count": len(candidates),
                        "unique_payload_count": len(by_hash),
                        "canonical_document_count": canonical_docs,
                        "alias_count": alias_count,
                        "chunk_count": chunk_count,
                    },
                    conn=conn,
                )

            snapshot = self.storage.get_snapshot(snapshot_id, conn=conn)
            if snapshot is None:
                raise RuntimeError("Snapshot write failed")

        return CorpusSnapshot(
            snapshot_id=int(snapshot["id"]),
            snapshot_name=str(snapshot["snapshot_name"]),
            root_path=str(snapshot["root_path"]),
            doc_count=int(snapshot["doc_count"]),
            unique_payload_count=int(snapshot["unique_payload_count"]),
            created_at=str(snapshot["created_at"]),
        )


class CorpusRefresher:
    """Re-read a live source and record one outcome per source (#54, MTR-018).

    A refresh is a freshness-recording pass, not a re-ingest: it never
    creates a snapshot, never duplicates a document row, and never rewrites
    history. What it records, per source, is a `source_versions` row:

    - ``ok`` — first observation of a source, or recovery after a
      ``deleted`` / ``revoked`` / failed marker. A new version row.
    - ``unchanged`` — same bytes as the latest content version: no new
      version row (idempotent replay), but the version's ``retrieved_at``
      advances to this read, so a just-confirmed source does not
      false-positive stale.
    - ``changed`` — different bytes: a new version under the same source id.
    - ``timeout`` / ``rate_limited`` / ``error`` — the read failed for this
      source only; the failure is recorded, the other sources still refresh,
      and the prior version stays usable-but-stale.
    - ``deleted`` — the file is gone from the root: a marker row, no bytes.
    - ``revoked`` — the file is present but the privacy inventory now
      refuses it: a marker row, bytes never read. The planner excludes it
      until re-admitted.

    Refresh runs over containment-admitted sources: discovery is the
    same `discover_documents` ingest uses, so the merged containment +
    privacy-classification guard (#33/#34) decides what may be read.
    The admission record (#48) gates *use*, not observation: a refresh
    re-reads a source whether or not it is admitted — otherwise no
    evidence could ever be gathered about an unadmitted source — except
    a source whose latest admission decision is ``revoked``: its bytes
    are never re-read, the same as an inventory-refused source, and the
    run records a ``revoked`` marker. Refresh never promotes a candidate
    to support — only a human judgment does (#50).
    """

    def __init__(self, storage: Storage, ledger: Ledger | None = None) -> None:
        self.storage = storage
        self.ledger = ledger

    def _record_marker(
        self,
        conn,
        record: dict,
        run_id: int,
        retrieved_at: str,
        outcome: str,
        detail: dict,
    ) -> None:
        self.storage.insert_source_version(
            int(record["id"]),
            None,
            str(run_id),
            retrieved_at,
            outcome,
            detail,
            conn=conn,
        )

    def _refresh_admitted(
        self,
        conn,
        root: Path,
        path: Path,
        rel_path: str,
        record: dict | None,
        max_age_hours: int | None,
        run_id: int,
        retrieved_at: str,
    ) -> tuple[str, dict]:
        """Re-read one admitted file; returns (outcome, detail)."""
        try:
            candidate = build_candidate(root, path)
        except RateLimitError:
            outcome, detail = "rate_limited", {"reason": "rate_limited"}
        except TimeoutError:
            outcome, detail = "timeout", {"reason": "timeout"}
        except OSError as exc:
            if exc.errno == errno.ETIMEDOUT:
                outcome, detail = "timeout", {"reason": "timeout"}
            else:
                outcome, detail = "error", {"reason": "read_error"}
        except ValueError as exc:
            outcome, detail = "error", {"reason": str(exc).split(":")[0]}
        else:
            return self._record_content(
                conn, candidate, root, rel_path, record, max_age_hours, run_id, retrieved_at
            )

        # A failed read still records its outcome for this source only.
        if record is None:
            record = self.storage.get_or_create_source_record(
                str(root),
                rel_path,
                max_age_hours if max_age_hours is not None else DEFAULT_MAX_AGE_HOURS,
                conn=conn,
            )
        elif max_age_hours is not None:
            self.storage.set_source_max_age(int(record["id"]), max_age_hours, conn=conn)
        content = self.storage.latest_content_version(int(record["id"]), conn=conn)
        self._record_marker(
            conn,
            record,
            run_id,
            retrieved_at,
            outcome,
            {**detail, "last_good_sha256": content["sha256"] if content else None},
        )
        return outcome, detail

    def _record_content(
        self,
        conn,
        candidate: CandidateDocument,
        root: Path,
        rel_path: str,
        record: dict | None,
        max_age_hours: int | None,
        run_id: int,
        retrieved_at: str,
    ) -> tuple[str, dict]:
        """Record a successful re-read; returns (outcome, detail).

        Same bytes as the latest content version with a healthy lineage:
        no new version row, the version's `retrieved_at` advances
        (idempotent replay). A new version row only when the bytes changed,
        or when the previous observation was a marker the read recovers
        from — the marker stays in history, the recovery is observed.
        """
        if record is None:
            record = self.storage.get_or_create_source_record(
                str(root),
                rel_path,
                max_age_hours if max_age_hours is not None else DEFAULT_MAX_AGE_HOURS,
                conn=conn,
            )
        elif max_age_hours is not None:
            self.storage.set_source_max_age(int(record["id"]), max_age_hours, conn=conn)
        record_id = int(record["id"])
        latest = self.storage.latest_source_version(record_id, conn=conn)
        content = self.storage.latest_content_version(record_id, conn=conn)
        if latest is not None and str(latest["outcome"]) not in REFRESH_CONTENT_OUTCOMES:
            # Recovery: the previous observation was a deleted / revoked /
            # failed marker. A new version row records the recovery even
            # when the bytes match the last good version.
            self.storage.insert_source_version(
                record_id,
                candidate.sha256,
                str(run_id),
                retrieved_at,
                "ok",
                {"recovered_after": str(latest["outcome"])},
                conn=conn,
            )
            return "ok", {"recovered_after": str(latest["outcome"])}
        if content is not None and str(content["sha256"]) == candidate.sha256:
            self.storage.touch_source_version(
                int(content["id"]), retrieved_at, conn=conn
            )
            return "unchanged", {}
        self.storage.insert_source_version(
            record_id,
            candidate.sha256,
            str(run_id),
            retrieved_at,
            "changed" if content is not None else "ok",
            {},
            conn=conn,
        )
        return ("changed" if content is not None else "ok"), {}

    def refresh(
        self,
        root: Path,
        max_age_hours: int | None = None,
    ) -> dict:
        """Re-read every admitted source under `root`; operator-triggered.

        `max_age_hours`, when given, becomes the freshness bound stored on
        every source record this run touches; new sources otherwise default
        to `DEFAULT_MAX_AGE_HOURS` (168). A scheduled invocation of this
        command is the scheduled form — no daemon in this build.
        """
        root = root.expanduser().resolve()
        if not root.exists() or not root.is_dir():
            raise ValueError(f"Invalid root directory: {root}")
        started_at = utcnow_iso()
        root_str = str(root)
        outcomes: dict[str, int] = {}
        per_source: list[dict] = []
        with self.storage.connection() as conn:
            run_id = self.storage.insert_refresh_run(root_str, started_at, conn=conn)
            admitted = {
                str(p.relative_to(root)): p for p in discover_documents(root)
            }
            present = {
                str(p.relative_to(root)): p
                for p in discover_documents(root, apply_inventory=False)
            }
            known = {
                r["rel_path"]: r
                for r in self.storage.list_source_records(root_path=root_str, conn=conn)
            }

            def note(rel_path: str, outcome: str) -> None:
                outcomes[outcome] = outcomes.get(outcome, 0) + 1
                per_source.append({"rel_path": rel_path, "outcome": outcome})

            # 1. Admitted files: re-read and compare against the last version.
            # A source whose latest admission decision is `revoked` is
            # recorded `revoked` without re-reading bytes (#48 step 4:
            # revoked documents are excluded from use, and observation
            # must not read bytes a decision has withdrawn).
            for rel_path in sorted(admitted):
                retrieved_at = utcnow_iso()
                latest_decision = self.storage.latest_source_admission(
                    root_str, rel_path, conn=conn
                )
                if (
                    latest_decision is not None
                    and str(latest_decision["decision"]) == "revoked"
                ):
                    record = known.get(rel_path)
                    if record is None:
                        record = self.storage.get_or_create_source_record(
                            root_str,
                            rel_path,
                            max_age_hours
                            if max_age_hours is not None
                            else DEFAULT_MAX_AGE_HOURS,
                            conn=conn,
                        )
                    self._record_marker(
                        conn,
                        record,
                        run_id,
                        retrieved_at,
                        "revoked",
                        {"reason": "admission_revoked"},
                    )
                    note(rel_path, "revoked")
                    continue
                outcome, _ = self._refresh_admitted(
                    conn,
                    root,
                    admitted[rel_path],
                    rel_path,
                    known.get(rel_path),
                    max_age_hours,
                    run_id,
                    retrieved_at,
                )
                note(rel_path, outcome)

            # 2. Known sources present but no longer admitted: revoked.
            for rel_path in sorted(set(present) - set(admitted)):
                record = known.get(rel_path)
                if record is None:
                    continue
                retrieved_at = utcnow_iso()
                self._record_marker(
                    conn,
                    record,
                    run_id,
                    retrieved_at,
                    "revoked",
                    {"reason": "admission_refused"},
                )
                note(rel_path, "revoked")

            # 3. Known sources absent from the root: deleted — unless the
            # path still exists in some unreadable form (symlink, socket),
            # which is a boundary error, not a deletion.
            for rel_path in sorted(set(known) - set(present)):
                record = known[rel_path]
                retrieved_at = utcnow_iso()
                if os.path.lexists(root / rel_path):
                    self._record_marker(
                        conn,
                        record,
                        run_id,
                        retrieved_at,
                        "error",
                        {"reason": "ERR_SOURCE_BOUNDARY"},
                    )
                    note(rel_path, "error")
                else:
                    self._record_marker(
                        conn,
                        record,
                        run_id,
                        retrieved_at,
                        "deleted",
                        {"reason": "absent_from_root"},
                    )
                    note(rel_path, "deleted")

            finished_at = utcnow_iso()
            self.storage.finish_refresh_run(run_id, outcomes, finished_at, conn=conn)
            if self.ledger is not None:
                self.ledger.append(
                    "corpus.refresh",
                    {
                        "refresh_run_id": run_id,
                        "root_path": root_str,
                        "outcome_counts": outcomes,
                        "sources": per_source,
                    },
                    conn=conn,
                )

        # Source admission (#48 step 7): a `private`-access source's path
        # never appears in output — the refresh summary redacts it like
        # every other surface. The observation itself is unchanged.
        from .admission import redact_rel_path

        redacted_sources: list[dict] = []
        for entry in per_source:
            decision = self.storage.latest_source_admission(
                root_str, str(entry["rel_path"])
            )
            access = str(decision["access"]) if decision is not None else None
            redacted_sources.append(
                {**entry, "rel_path": redact_rel_path(str(entry["rel_path"]), access)}
            )

        return {
            "schema_version": "1.0",
            "refresh_run_id": run_id,
            "root_path": root_str,
            "started_at": started_at,
            "finished_at": finished_at,
            "outcome_counts": outcomes,
            "sources": redacted_sources,
        }
