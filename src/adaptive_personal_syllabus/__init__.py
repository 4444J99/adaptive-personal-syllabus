"""adaptive-personal-syllabus — Part of the organvm eight-organ system."""

__version__ = "0.6.0"

# Minimal public surface (ADR 005, #42 MTR-008): the supported interface is
# the three CLI entry points (`syllabus`/`aps` -> core:cli,
# `aps-data-export` -> data_export:main) plus the package version. The
# importable module API is internal — no stability promise.
__all__ = ["__version__"]
