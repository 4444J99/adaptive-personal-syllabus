"""Tests for corpus ingestion and chunking."""

from __future__ import annotations

from pathlib import Path

import pytest

from adaptive_personal_syllabus.corpus import (
    CorpusIngestor,
    discover_documents,
    heading_aware_chunks,
)
from adaptive_personal_syllabus.ledger import Ledger
from adaptive_personal_syllabus.storage import Storage


def test_discover_documents_filters_supported_extensions(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("# hi\nbody", encoding="utf-8")
    (tmp_path / "b.py").write_text("print('x')", encoding="utf-8")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "hidden.md").write_text("ignore", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "c.json").write_text('{"x": 1}', encoding="utf-8")

    docs = discover_documents(tmp_path)
    rels = [str(p.relative_to(tmp_path)) for p in docs]

    assert rels == ["a.md", "docs/c.json"]


def test_heading_aware_chunks() -> None:
    chunks = heading_aware_chunks(
        """# Root
Intro line
## Child
Child line
### Leaf
Leaf line
"""
    )
    assert chunks[0][0] == "Root"
    assert "Intro" in chunks[0][1]
    assert chunks[1][0] == "Root / Child"
    assert chunks[2][0] == "Root / Child / Leaf"


def test_corpus_ingest_dedup_and_chunks(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("# Title\nhello world", encoding="utf-8")
    (tmp_path / "b.md").write_text("# Title\nhello world", encoding="utf-8")  # duplicate content
    (tmp_path / "c.json").write_text('{"ok": true}', encoding="utf-8")

    db_path = tmp_path / "test.db"
    storage = Storage(db_path)
    ledger = Ledger(storage)
    snapshot = CorpusIngestor(storage, ledger).ingest(tmp_path, "snap-1")

    assert snapshot.doc_count == 3
    assert snapshot.unique_payload_count == 2
    assert snapshot.snapshot_id > 0

    stats = storage.corpus_stats()
    assert stats["document_count"] == 2
    assert stats["alias_count"] == 1
    assert stats["chunk_count"] >= 2

    with storage.connection() as conn:
        canonical = conn.execute(
            "SELECT canonical_path FROM documents WHERE rel_path = 'a.md'"
        ).fetchone()
        alias = conn.execute("SELECT alias_path FROM document_aliases").fetchone()

    assert canonical is not None
    assert canonical["canonical_path"].endswith("a.md")
    assert alias is not None
    assert str(alias["alias_path"]).endswith("b.md")


def test_corpus_ingest_preserves_multiple_snapshots(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    storage = Storage(db_path)
    ledger = Ledger(storage)
    ingestor = CorpusIngestor(storage, ledger)

    root_a = tmp_path / "corpus-a"
    root_a.mkdir()
    (root_a / "a.md").write_text("# A\nalpha", encoding="utf-8")
    snap_a = ingestor.ingest(root_a, "snap-a")

    root_b = tmp_path / "corpus-b"
    root_b.mkdir()
    (root_b / "b.md").write_text("# B\nbeta", encoding="utf-8")
    (root_b / "c.json").write_text('{"ok": true}', encoding="utf-8")
    snap_b = ingestor.ingest(root_b, "snap-b")

    assert snap_a.snapshot_id != snap_b.snapshot_id

    stats_latest = storage.corpus_stats()
    assert stats_latest["snapshot"]["snapshot_name"] == "snap-b"
    assert stats_latest["document_count"] == 2

    stats_a_by_name = storage.corpus_stats(snapshot_name="snap-a")
    assert stats_a_by_name["snapshot"]["snapshot_name"] == "snap-a"
    assert stats_a_by_name["document_count"] == 1

    stats_b_by_id = storage.corpus_stats(snapshot_id=snap_b.snapshot_id)
    assert stats_b_by_id["snapshot"]["snapshot_name"] == "snap-b"
    assert stats_b_by_id["document_count"] == 2


def test_corpus_ingest_rejects_malformed_json(tmp_path: Path) -> None:
    (tmp_path / "bad.json").write_text('{"x": }', encoding="utf-8")
    db_path = tmp_path / "test.db"
    storage = Storage(db_path)
    ledger = Ledger(storage)

    with pytest.raises(ValueError, match="Malformed JSON"):
        CorpusIngestor(storage, ledger).ingest(tmp_path, "snap-bad")


def test_corpus_ingest_rejects_malformed_yaml(tmp_path: Path) -> None:
    (tmp_path / "bad.yaml").write_text("a: [1, 2", encoding="utf-8")
    db_path = tmp_path / "test.db"
    storage = Storage(db_path)
    ledger = Ledger(storage)

    with pytest.raises(ValueError, match="ERR_MALFORMED_YAML"):
        CorpusIngestor(storage, ledger).ingest(tmp_path, "snap-bad-yaml")
