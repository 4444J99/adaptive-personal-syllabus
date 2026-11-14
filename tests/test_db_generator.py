"""Tests for DatabaseSyllabusGenerator — instantiation and module building."""

from __future__ import annotations

from unittest.mock import patch

from adaptive_personal_syllabus.db_generator import DatabaseSyllabusGenerator
from adaptive_personal_syllabus.models import DifficultyLevel, LearnerProfile


def test_db_generator_url_passthrough():
    """Non-postgresql URLs are left unchanged (for testing)."""
    with patch("adaptive_personal_syllabus.db_generator.create_engine") as mock_ce:
        DatabaseSyllabusGenerator("sqlite:///test.db")
        mock_ce.assert_called_once_with("sqlite:///test.db")


def test_db_generator_url_normalization():
    """postgresql:// is rewritten to postgresql+psycopg:// for sync driver."""
    with patch("adaptive_personal_syllabus.db_generator.create_engine") as mock_ce:
        DatabaseSyllabusGenerator("postgresql://user:pass@host/db")
        mock_ce.assert_called_once_with("postgresql+psycopg://user:pass@host/db")


def test_db_generator_url_already_psycopg():
    """URLs with +psycopg are not double-rewritten."""
    with patch("adaptive_personal_syllabus.db_generator.create_engine") as mock_ce:
        DatabaseSyllabusGenerator("postgresql+psycopg://user:pass@host/db")
        mock_ce.assert_called_once_with("postgresql+psycopg://user:pass@host/db")


def test_build_modules_empty_taxonomy():
    """_build_modules returns empty list when taxonomy has no matching organ."""
    with patch("adaptive_personal_syllabus.db_generator.create_engine"):
        gen = DatabaseSyllabusGenerator("sqlite:///:memory:")
    profile = LearnerProfile(
        name="test", organs_of_interest=["I"], level=DifficultyLevel.BEGINNER
    )
    modules = gen._build_modules(profile, taxonomy=[], readings=[])
    assert modules == []


def test_build_modules_with_data():
    """_build_modules produces modules from matching taxonomy and readings."""
    with patch("adaptive_personal_syllabus.db_generator.create_engine"):
        gen = DatabaseSyllabusGenerator("sqlite:///:memory:")
    profile = LearnerProfile(
        name="test", organs_of_interest=["I"], level=DifficultyLevel.BEGINNER
    )
    taxonomy = [
        {
            "slug": "i-theoria",
            "label": "Theoria",
            "organ_id": 1,
            "description": "Theory organ",
            "children": [
                {"slug": "foundations", "label": "Foundations", "description": "Base concepts"},
            ],
        }
    ]
    readings = [
        {
            "title": "Intro to Theoria",
            "author": "Test",
            "organ_tags": ["i-theoria"],
            "difficulty": "beginner",
            "source_type": "book",
        }
    ]
    modules = gen._build_modules(profile, taxonomy, readings)
    assert len(modules) == 1
    assert modules[0].title == "Foundations"
    assert modules[0].organ == "i-theoria"
    assert "Intro to Theoria" in modules[0].readings


def test_unassessed_does_not_filter_readings_as_advanced():
    """An unassessed preference does not establish a proficiency filter."""
    gen = DatabaseSyllabusGenerator("sqlite:///:memory:")
    profile = LearnerProfile(name="Synthetic", organs_of_interest=["I"])
    taxonomy = [{
        "slug": "i-theoria", "label": "Theoria",
        "children": [{"slug": "foundations", "label": "Foundations"}],
    }]
    readings = [
        {"title": level, "organ_tags": ["i-theoria"], "difficulty": level}
        for level in ("beginner", "intermediate", "advanced")
    ]
    modules = gen._build_modules(profile, taxonomy, readings)
    assert modules[0].difficulty == DifficultyLevel.UNASSESSED
    assert modules[0].readings == ["beginner", "intermediate", "advanced"]
