"""Tests for adaptive_personal_syllabus data_export — sample learning paths."""
import json
from pathlib import Path

import pytest

from adaptive_personal_syllabus.data_export import (
    SAMPLE_PROFILES,
    export_all,
    generate_sample_paths,
)

# Synthetic seed fixture (tests/fixtures/seed): the suite must pass on a
# clean public checkout with no sibling koinonia-db clone (#42, MTR-008).
# The real seed is exercised only when the sibling checkout is present
# (test_generate_sample_paths_real_seed below, skipped otherwise, as in
# test_ingest_canary.py).
FIXTURE_SEED_DIR = Path(__file__).parent / "fixtures" / "seed"
SEED_DIR = FIXTURE_SEED_DIR
REAL_SEED_DIR = Path(__file__).parent.parent.parent / "koinonia-db" / "seed"


def test_sample_profiles_defined():
    """Three sample profiles exist for beginner/intermediate/advanced."""
    assert len(SAMPLE_PROFILES) == 3
    levels = {p.level.value for p in SAMPLE_PROFILES}
    assert levels == {"beginner", "intermediate", "advanced"}


def test_generate_sample_paths():
    """Generates 3 paths with modules."""
    paths = generate_sample_paths(SEED_DIR)
    assert len(paths) == 3
    for p in paths:
        assert "path_id" in p
        assert "title" in p
        assert "total_hours" in p
        assert "modules" in p
        assert p["module_count"] > 0
        assert p["total_hours"] > 0


def test_path_module_structure():
    """Each module in generated paths has expected fields."""
    paths = generate_sample_paths(SEED_DIR)
    for p in paths:
        for m in p["modules"]:
            assert "module_id" in m
            assert "title" in m
            assert "organ" in m
            assert "difficulty" in m
            assert "readings" in m
            assert "questions" in m
            assert "estimated_hours" in m


def test_export_all_writes_file(tmp_path):
    """export_all writes the sample paths JSON to the output directory."""
    paths = export_all(seed_dir=SEED_DIR, output_dir=tmp_path)
    assert len(paths) == 1

    out_path = tmp_path / "sample-learning-paths.json"
    assert out_path.exists()
    data = json.loads(out_path.read_text())
    assert len(data) == 3
    assert data[0]["module_count"] > 0


def test_generate_sample_paths_real_seed():
    """Real koinonia-db seed generates non-empty paths — CI only.

    Skipped on a clean public checkout (no sibling clone), where the
    synthetic fixture covers the same assertions above.
    """
    if not (REAL_SEED_DIR / "taxonomy.json").exists():
        pytest.skip("koinonia-db seed not present; real-seed leg runs in CI")
    paths = generate_sample_paths(REAL_SEED_DIR)
    assert len(paths) == 3
    for p in paths:
        assert p["module_count"] > 0
        assert p["total_hours"] > 0
