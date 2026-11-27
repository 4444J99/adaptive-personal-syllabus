"""adaptive-personal-syllabus — Part of the organvm eight-organ system."""

import importlib.metadata

# Fallback version for a source checkout without an installed distribution
# (ADR 008, #53): the package version has exactly one source of truth, the
# installed distribution metadata written from pyproject.toml. The literal
# below is only the checkout fallback, and tests/test_compatibility.py pins
# it to the pyproject version, so it cannot drift silently.
_FALLBACK_VERSION = "0.6.0"


def _resolve_version() -> str:
    """Return the installed distribution version, or the checkout fallback."""
    try:
        return importlib.metadata.version("adaptive-personal-syllabus")
    except importlib.metadata.PackageNotFoundError:
        return _FALLBACK_VERSION


__version__ = _resolve_version()

# Minimal public surface (ADR 005, #42 MTR-008): the supported interface is
# the three CLI entry points (`syllabus`/`aps` -> core:cli,
# `aps-data-export` -> data_export:main) plus the package version. The
# importable module API is internal — no stability promise.
__all__ = ["__version__"]
