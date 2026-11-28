"""Release-artifact contract tests (ADR 011, #57).

Pins the release rail so the next drift fails CI instead of shipping:
the koinonia-db pin in pyproject.toml matches the commit CI checks out,
the release workflow builds reproducibly and publishes only on a tag,
the sdist ships the sample seed, and the quick-start documents the
stranger path (checksum verification, version check, no checkout).
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


def _pyproject() -> dict:
    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)


def test_koinonia_db_pin_matches_ci_checkout() -> None:
    """The pinned git URL in pyproject.toml is the commit CI checks out."""
    deps = _pyproject()["project"]["dependencies"]
    pinned = [d for d in deps if d.startswith("koinonia-db @ ")]
    assert len(pinned) == 1, f"expected one koinonia-db dependency, got {deps}"
    match = re.fullmatch(
        r"koinonia-db @ git\+https://github\.com/4444J99/koinonia-db\.git@([0-9a-f]{40})",
        pinned[0],
    )
    assert match is not None, f"koinonia-db dependency is not a pinned git URL: {pinned[0]}"
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert match.group(1) in ci, (
        "pyproject pin and CI checkout disagree on the koinonia-db commit"
    )


def test_release_workflow_builds_reproducibly() -> None:
    """The release workflow checks wheel bytes and sdist member contents."""
    workflow = yaml.safe_load(
        (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    )
    build_steps = workflow["jobs"]["build"]["steps"]
    build_text = "\n".join(str(s.get("run", "")) for s in build_steps)
    assert "SOURCE_DATE_EPOCH" in build_text
    assert "python -m build" in build_text
    assert "sha256sum" in build_text
    assert "diff SHA256SUMS-a.txt SHA256SUMS-b.txt" in build_text
    assert "tarfile" in build_text  # sdist compared by member contents, not raw bytes


def test_release_job_publishes_only_on_tag() -> None:
    """The release job fires on v* tags and needs contents: write; nothing else does."""
    workflow = yaml.safe_load(
        (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    )
    assert workflow["permissions"] == {"contents": "read"}
    release = workflow["jobs"]["release"]
    assert release["if"] == "startsWith(github.ref, 'refs/tags/v')"
    assert release["permissions"] == {"contents": "write"}
    release_text = "\n".join(str(s.get("run", "")) for s in release["steps"])
    assert "gh release create" in release_text
    assert "SHA256SUMS" in release_text
    assert "DEPENDENCY-BILL.txt" in release_text


def test_sdist_ships_the_sample_seed() -> None:
    """MANIFEST.in grafts the synthetic seed, so the sdist carries it."""
    manifest = (REPO_ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    assert "graft tests/fixtures/seed" in manifest
    assert (REPO_ROOT / "tests" / "fixtures" / "seed" / "taxonomy.json").is_file()
    assert (REPO_ROOT / "tests" / "fixtures" / "seed" / "reading_lists.json").is_file()


def test_quickstart_documents_the_stranger_path() -> None:
    """QUICKSTART verifies checksums and version, and needs no checkout."""
    text = (REPO_ROOT / "docs" / "QUICKSTART.md").read_text(encoding="utf-8")
    assert "sha256sum -c SHA256SUMS" in text
    assert "syllabus version" in text
    assert "v0.6.0" in text
    assert "no checkout" in text
    assert "no credentials" in text
    assert "tests/fixtures/seed" in text


def test_adr_011_records_the_decision() -> None:
    """ADR 011 names the chosen artifact and rejects PyPI with its reason."""
    text = (REPO_ROOT / "docs" / "adr" / "011-release-artifact.md").read_text(
        encoding="utf-8"
    )
    assert "GitHub release" in text
    assert "PyPI is rejected" in text
    assert "archived and unpublished" in text
