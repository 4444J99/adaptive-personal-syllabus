"""Public/private component contract tests (adaptive-personal-syllabus #42, MTR-008).

The contract ADR 005 declares the minimal public surface: the three CLI
entry points (`syllabus`/`aps` -> core:cli, `aps-data-export`) plus the
package version. The importable module API is internal — no stability
promise. These tests enforce that contract and the private-input denial
through the public surface itself (the CLI), not through module internals.
Synthetic canaries only — never real secrets or personal data.
"""

from __future__ import annotations

import ast
import json
import shutil
import sys
import tomllib
from pathlib import Path

from click.testing import CliRunner

import adaptive_personal_syllabus as aps
from adaptive_personal_syllabus.core import cli
from adaptive_personal_syllabus.storage import Storage

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src" / "adaptive_personal_syllabus"
INVENTORY_SRC = REPO_ROOT / "docs" / "privacy-classification.yaml"

PUBLIC_CANARY = "CANARY-PUBLIC-CONTENT-9c41d2"
PRIVATE_CANARY = "CANARY-PRIVATE-CONTENT-4b07e8"

# Home-path literals, assembled from parts on purpose: this file is itself
# scanned by tests/test_privacy_classification.py, so it must not contain
# the literals it detects.
_HOME_USERS = "/" + "Users" + "/"
_HOME_HOME = "/" + "home" + "/"
_HOME_TILDE = "~" + "/"


def test_public_surface_is_declared_and_minimal() -> None:
    """`__all__` names exactly the supported surface: the version only.

    The star-import half runs in a subprocess: `exec` is banned by the
    repo's ruff rules (S102), and a star import at this module's top level
    would pollute the test namespace.
    """
    import subprocess

    assert aps.__all__ == ["__version__"]
    code = (
        "from adaptive_personal_syllabus import *; "
        "assert '__version__' in dir(); "
        "assert [n for n in dir() if not n.startswith('_')] == []; "
        "print('star-ok')"
    )
    env = {"PYTHONPATH": str(REPO_ROOT / "src"), "PATH": "/usr/bin:/bin"}
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    assert "star-ok" in proc.stdout


def test_version_matches_pyproject_and_cli() -> None:
    """pyproject version, `__version__`, and `syllabus version` cannot drift.

    The drift (pyproject 0.6.0 vs `__version__` 0.5.0) found by #42's step-1
    reproduction is the regression this test guards.
    """
    with open(REPO_ROOT / "pyproject.toml", "rb") as f:
        declared = tomllib.load(f)["project"]["version"]
    assert aps.__version__ == declared
    result = CliRunner().invoke(cli, ["version"])
    assert result.exit_code == 0
    assert declared in result.output


def test_no_private_imports_or_ambient_credentials() -> None:
    """No src module imports a private root or reads ambient credentials.

    Mirrors the #42 plan's verified grep at main `363c7b1c`: no
    `organvm`/`private` imports, no `os.environ`/`getenv`, no hardcoded
    home-path literals. `expanduser()` on caller-supplied paths is allowed
    (it is not a hardcoded path); the secret-pattern constants in
    `docs_audit.py` are redaction machinery, not credentials.
    """
    for path in sorted(SRC_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    assert root not in {"organvm", "private"}, f"{path.name}: {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".")[0]
                assert root not in {"organvm", "private"}, f"{path.name}: {node.module}"
            elif isinstance(node, ast.Attribute):
                if node.attr == "environ" and isinstance(node.value, ast.Name):
                    assert node.value.id != "os", f"{path.name}: os.environ"
                assert node.attr != "getenv", f"{path.name}: getenv"
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id != "getenv", f"{path.name}: getenv"
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert _HOME_USERS not in node.value, f"{path.name}: hardcoded home path"
                assert _HOME_HOME not in node.value, f"{path.name}: hardcoded home path"
                assert not node.value.startswith(_HOME_TILDE), f"{path.name}: hardcoded home path"


def test_private_input_refused_through_cli(tmp_path: Path) -> None:
    """Through the CLI, a private-classified file is refused at admission.

    A public file's canary is ingested; a private-classified file's canary
    (same corpus, same run) never reaches the store. This is the #34
    admission predicate exercised through the declared public surface.
    """
    assert INVENTORY_SRC.exists(), f"live inventory missing: {INVENTORY_SRC}"
    root = tmp_path / "corpus"
    (root / "docs").mkdir(parents=True)
    shutil.copyfile(INVENTORY_SRC, root / "docs" / "privacy-classification.yaml")
    (root / "notes.md").write_text(
        f"# Notes\nThe draft mentions {PUBLIC_CANARY} in passing.\n", encoding="utf-8"
    )
    (root / ".env.local.md").write_text(
        f"# Local config\nThe draft mentions {PRIVATE_CANARY} in passing.\n",
        encoding="utf-8",
    )

    db_path = tmp_path / "surface.db"
    result = CliRunner().invoke(
        cli,
        [
            "corpus",
            "ingest",
            "--root",
            str(root),
            "--snapshot",
            "surface-sweep",
            "--db-path",
            str(db_path),
        ],
    )
    assert result.exit_code == 0, result.output
    snapshot_id = json.loads(result.output)["snapshot"]["snapshot_id"]

    chunks = Storage(db_path).list_document_chunks(snapshot_id=snapshot_id)
    texts = [chunk["text"] for chunk in chunks]
    assert any(PUBLIC_CANARY in text for text in texts), "public canary missing"
    assert not any(PRIVATE_CANARY in text for text in texts), "private canary admitted"


def test_package_imports_with_no_private_input_present() -> None:
    """Importing the package needs no private input and touches nothing.

    The import surface is side-effect free: it succeeds in a bare
    interpreter with no profile, corpus, database, or credentials present.
    """
    code = (
        "import sys; sys.path.insert(0, "
        f"{str(REPO_ROOT / 'src')!r}); "
        "import adaptive_personal_syllabus as m; "
        "assert m.__version__; assert m.__all__ == ['__version__']; "
        "print('import-ok')"
    )
    import subprocess

    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "import-ok" in proc.stdout
