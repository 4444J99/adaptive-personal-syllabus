"""Corpus ingestion and document chunking utilities."""
from __future__ import annotations

import csv
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

from .ledger import Ledger
from .models import CorpusSnapshot
from .storage import Storage, utcnow_iso

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


def discover_documents(root: Path, exclude_paths: set[Path] | None = None) -> list[Path]:
    """Discover regular files; symlink aliases are not admitted sources."""
    root = root.expanduser().resolve(strict=True)
    excluded = {p.expanduser().resolve() for p in (exclude_paths or set())}

    def allowed(path: Path) -> bool:
        if path.is_symlink() or _should_skip(path, root):
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


class CorpusIngestor:
    """Ingest repository corpus, deduplicate by content hash, and persist chunks."""

    def __init__(self, storage: Storage, ledger: Ledger | None = None) -> None:
        self.storage = storage
        self.ledger = ledger

    def _build_candidate(self, root: Path, path: Path) -> CandidateDocument:
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
                group = sorted(by_hash[sha], key=lambda c: c.rel_path)
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
