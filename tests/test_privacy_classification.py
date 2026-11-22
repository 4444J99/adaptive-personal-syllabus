"""Repository-boundary classification contract (adaptive-personal-syllabus #33).

Guards the boundary the #33 plan establishes: no forbidden artifact class is
tracked, no absolute home-directory path is tracked, and every tracked path
is covered by exactly one entry in docs/privacy-classification.yaml.

The home-path detector pattern is assembled from parts on purpose: this file
is itself scanned, so it must not contain the literal it detects.
"""

from __future__ import annotations

import fnmatch
import re
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = REPO_ROOT / "docs" / "privacy-classification.yaml"

CLASSES = ("public", "private-never-in-git", "review")

# Forbidden tracked-path classes (#33 step 1). Patterns use fnmatch over the
# whole relative path, so `*` crosses `/`.
FORBIDDEN_PATTERNS = (
    "*.db",
    "*.sqlite",
    "*.sqlite3",
    "*.sqlite-*",
    "*.db-journal",
    "*.db-wal",
    "*.db-shm",
    "*__pycache__/*",
    "*.pyc",
    "*.pyo",
    "*.egg-info",
    "*.egg-info/*",
    ".env*",
    "*/.env*",
    "*.private/*",
    "*.secrets/*",
    "*.adaptive-syllabus/*",
    "docs-audit-ci.*",
    ".coverage",
    "htmlcov/*",
    "*.pytest_cache/*",
    "*.mypy_cache/*",
    "*.ruff_cache/*",
)

_HOME_USER = "/" + "Users" + "/"
_HOME_HOME = "/" + "home" + "/"
HOME_PATH_RE = re.compile(re.escape(_HOME_USER) + "|" + re.escape(_HOME_HOME))

# Suffixes whose bytes are never scanned as text.
BINARY_SUFFIXES = {".db", ".pyc", ".pyo", ".png", ".jpg", ".jpeg", ".gif", ".ico"}


def tracked_paths() -> list[str]:
    """Tracked paths at the checkout head, via `git ls-files`."""
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def is_forbidden(path: str) -> bool:
    """True when a tracked path belongs to a forbidden artifact class."""
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in FORBIDDEN_PATTERNS)


def contains_home_path(text: str) -> bool:
    """True when text carries an absolute home-directory path literal."""
    return HOME_PATH_RE.search(text) is not None


def _match_parts(pattern_parts: list[str], parts: list[str]) -> bool:
    if not pattern_parts:
        return not parts
    head, rest = pattern_parts[0], pattern_parts[1:]
    if head == "**":
        return any(_match_parts(rest, parts[i:]) for i in range(len(parts) + 1))
    if not parts:
        return False
    return fnmatch.fnmatchcase(parts[0], head) and _match_parts(rest, parts[1:])


def inventory_match(pattern: str, path: str) -> bool:
    """Match one inventory pattern against a tracked path.

    `*` matches within one path segment; `**` matches zero or more segments.
    """
    return _match_parts(pattern.split("/"), path.split("/"))


def load_inventory() -> dict:
    """The classification inventory as data."""
    return yaml.safe_load(INVENTORY_PATH.read_text(encoding="utf-8"))


def test_no_forbidden_tracked_path() -> None:
    """No tracked path belongs to a forbidden artifact class (#33 step 1)."""
    bad = [path for path in tracked_paths() if is_forbidden(path)]
    assert not bad, f"forbidden paths are tracked: {bad}"


def test_forbidden_matcher_negative_controls() -> None:
    """The forbidden matcher flags synthetic forbidden paths, not clean ones."""
    for path in (
        "audit.db",
        "data/store.sqlite3",
        "src/x/__pycache__/mod.pyc",
        "src/x.egg-info/PKG-INFO",
        ".env",
        "config/.env.local",
        ".private/notes.md",
        "docs/.secrets/key.txt",
        "docs-audit-ci.db",
        ".coverage",
    ):
        assert is_forbidden(path), f"matcher missed forbidden path: {path}"
    for path in (
        "src/adaptive_personal_syllabus/core.py",
        "tests/test_core.py",
        "docs/privacy-classification.yaml",
        "data/sample-learning-paths.json",
        "pyproject.toml",
    ):
        assert not is_forbidden(path), f"matcher flagged clean path: {path}"


def test_no_absolute_home_path_in_tracked_files() -> None:
    """No tracked text file carries an absolute home-directory path (#33)."""
    hits: list[str] = []
    for path in tracked_paths():
        if Path(path).suffix in BINARY_SUFFIXES:
            continue
        try:
            text = (REPO_ROOT / path).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if contains_home_path(text):
            hits.append(path)
    assert not hits, f"absolute home paths in tracked files: {hits}"


def test_home_path_detector_flags_synthetic_canary(tmp_path: Path) -> None:
    """The detector catches a planted synthetic home path (canary, #33 step 1)."""
    canary = tmp_path / "canary.md"
    canary.write_text("root: " + _HOME_USER + "canary-user/Workspace/repo/docs\n")
    assert contains_home_path(canary.read_text(encoding="utf-8"))
    clean = tmp_path / "clean.md"
    clean.write_text("root: docs\n")
    assert not contains_home_path(clean.read_text(encoding="utf-8"))


def test_inventory_covers_every_tracked_path_exactly_once() -> None:
    """Every tracked path is classified by exactly one inventory entry."""
    inventory = load_inventory()
    entries = inventory["entries"]
    for entry in entries:
        assert entry["class"] in CLASSES, f"unknown class: {entry}"
        assert entry["patterns"], f"entry without patterns: {entry}"
    uncovered: list[str] = []
    ambiguous: list[str] = []
    for path in tracked_paths():
        matches = [
            entry
            for entry in entries
            if any(inventory_match(pattern, path) for pattern in entry["patterns"])
        ]
        if not matches:
            uncovered.append(path)
        elif len(matches) > 1:
            ambiguous.append(path)
    assert not uncovered, f"tracked paths with no inventory entry: {uncovered}"
    assert not ambiguous, f"tracked paths matching several entries: {ambiguous}"


def test_inventory_entries_each_describe_live_paths() -> None:
    """Public/review entries each match at least one tracked path."""
    inventory = load_inventory()
    paths = tracked_paths()
    for entry in inventory["entries"]:
        if entry["class"] == "private-never-in-git":
            continue
        matched = [
            path
            for path in paths
            if any(inventory_match(pattern, path) for pattern in entry["patterns"])
        ]
        assert matched, f"entry matches nothing: {entry['patterns']}"
