"""Synthetic source-admission boundaries; no personal data fixtures."""

from pathlib import Path

import pytest

from adaptive_personal_syllabus.corpus import CorpusIngestor, discover_documents
from adaptive_personal_syllabus.storage import Storage


def test_discovery_never_follows_file_links(tmp_path: Path) -> None:
    root = tmp_path / "admitted"
    root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("synthetic private canary")
    (root / "link.md").symlink_to(outside)
    (root / "real.md").write_text("admitted text")
    (root / "alias.md").symlink_to(root / "real.md")
    assert [p.name for p in discover_documents(root)] == ["real.md"]


def test_candidate_rejects_link_swap_before_read(tmp_path: Path) -> None:
    root = tmp_path / "admitted"
    root.mkdir()
    source = root / "source.md"
    source.write_text("original")
    selected = discover_documents(root)[0]
    outside = tmp_path / "outside.md"
    outside.write_text("synthetic private canary")
    source.unlink()
    source.symlink_to(outside)
    ingestor = CorpusIngestor(Storage(tmp_path / "db.sqlite"))
    with pytest.raises(ValueError, match="ERR_SOURCE_BOUNDARY"):
        ingestor._build_candidate(root, selected)


def test_candidate_rejects_parent_directory_swap(tmp_path: Path) -> None:
    root = tmp_path / "admitted"
    child = root / "child"
    child.mkdir(parents=True)
    (child / "source.md").write_text("original")
    selected = discover_documents(root)[0]
    child.rename(root / "original-child")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "source.md").write_text("synthetic canary")
    child.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="ERR_SOURCE_BOUNDARY"):
        CorpusIngestor(Storage(tmp_path / "db.sqlite"))._build_candidate(root, selected)


def test_private_and_explicitly_excluded_subtrees_are_not_discovered(tmp_path: Path) -> None:
    for name in (".private", ".secrets", ".adaptive-syllabus", "excluded", "public"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "source.md").write_text("synthetic")
    assert [str(p.relative_to(tmp_path)) for p in discover_documents(
        tmp_path, exclude_paths={tmp_path / "excluded"}
    )] == ["public/source.md"]


def test_failed_candidate_build_does_not_commit_snapshot(tmp_path: Path, monkeypatch) -> None:
    from adaptive_personal_syllabus import corpus

    root = tmp_path / "admitted"
    root.mkdir()
    source = root / "source.md"
    source.write_text("original")
    outside = tmp_path / "outside.md"
    outside.write_text("synthetic canary")

    def swapped(*args, **kwargs):
        selected = discover_documents(*args, **kwargs)
        source.unlink()
        source.symlink_to(outside)
        return selected

    monkeypatch.setattr(corpus, "discover_documents", swapped)
    storage = Storage(tmp_path / "db.sqlite")
    with pytest.raises(ValueError, match="ERR_SOURCE_BOUNDARY"):
        CorpusIngestor(storage).ingest(root, "must-not-commit")
    with storage.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 0
