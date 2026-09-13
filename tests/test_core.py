"""Tests for adaptive-personal-syllabus."""
from adaptive_personal_syllabus.generator import SyllabusGenerator
from adaptive_personal_syllabus.models import (
    DifficultyLevel,
    LearnerProfile,
    LearningModule,
    LearningPath,
)


def test_learner_profile_defaults():
    profile = LearnerProfile(name="Test")
    assert profile.level == DifficultyLevel.UNASSESSED
    assert profile.organs_of_interest == []
    assert profile.progress_pct == 0.0


def test_learner_profile_progress():
    profile = LearnerProfile(name="Test", completed_modules=["m1", "m2", "m3"])
    assert profile.progress_pct == 30.0


def test_learner_profile_progress_with_total():
    profile = LearnerProfile(
        name="Test", completed_modules=["m1", "m2"], total_modules=5
    )
    assert profile.progress_pct == 40.0


def test_learning_module():
    mod = LearningModule(
        module_id="test-01",
        title="Test Module",
        organ="i-theoria",
        difficulty=DifficultyLevel.BEGINNER,
    )
    assert mod.estimated_hours == 2.0
    assert mod.prerequisites == []


def test_learning_path_total_hours():
    profile = LearnerProfile(name="Test")
    path = LearningPath(
        path_id="p1",
        title="Test Path",
        learner=profile,
        modules=[
            LearningModule(
                module_id="m1",
                title="M1",
                organ="i",
                difficulty=DifficultyLevel.BEGINNER,
                estimated_hours=2.0,
            ),
            LearningModule(
                module_id="m2",
                title="M2",
                organ="i",
                difficulty=DifficultyLevel.BEGINNER,
                estimated_hours=3.0,
            ),
        ],
    )
    assert path.total_hours == 5.0
    assert path.module_count == 2


def test_learning_path_next_module():
    profile = LearnerProfile(name="Test", completed_modules=["m1"])
    path = LearningPath(
        path_id="p1",
        title="Test Path",
        learner=profile,
        modules=[
            LearningModule(
                module_id="m1", title="M1", organ="i", difficulty=DifficultyLevel.BEGINNER
            ),
            LearningModule(
                module_id="m2", title="M2", organ="i", difficulty=DifficultyLevel.BEGINNER
            ),
        ],
    )
    nxt = path.next_module()
    assert nxt is not None
    assert nxt.module_id == "m2"


def test_generator_creates_path():
    gen = SyllabusGenerator()
    profile = LearnerProfile(
        name="Test", organs_of_interest=["I"], level=DifficultyLevel.BEGINNER
    )
    path = gen.generate(profile)
    assert path.module_count > 0
    assert path.title.startswith("Learning Path:")


def test_generator_multiple_organs():
    gen = SyllabusGenerator()
    profile = LearnerProfile(
        name="Test", organs_of_interest=["I", "V"], level=DifficultyLevel.INTERMEDIATE
    )
    path = gen.generate(profile)
    organs = {m.organ for m in path.modules}
    assert len(organs) >= 1  # at least one organ represented


def test_generator_filters_completed():
    gen = SyllabusGenerator()
    profile1 = LearnerProfile(
        name="Test", organs_of_interest=["I"], level=DifficultyLevel.BEGINNER
    )
    path1 = gen.generate(profile1)

    if path1.modules:
        completed_id = path1.modules[0].module_id
        profile2 = LearnerProfile(
            name="Test",
            organs_of_interest=["I"],
            level=DifficultyLevel.BEGINNER,
            completed_modules=[completed_id],
        )
        path2 = gen.generate(profile2)
        assert path2.module_count == path1.module_count - 1
