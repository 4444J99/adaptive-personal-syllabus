"""Canary coverage for ingest admission and audit outputs (adaptive-personal-syllabus #34).

Synthetic canaries only — never real secrets or personal data. The secret-like
canary is assembled from parts on purpose: this file is itself scanned by the
repo's secret-pattern CI, so it must not contain the assembled literal.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from adaptive_personal_syllabus.corpus import discover_documents
from adaptive_personal_syllabus.docs_audit import DocsAuditService, write_report
from adaptive_personal_syllabus.ledger import Ledger
from adaptive_personal_syllabus.storage import Storage

REPO_ROOT = Path(__file__).resolve().parents[1]
INVENTORY_SRC = REPO_ROOT / "docs" / "privacy-classification.yaml"
SEED_DIR = REPO_ROOT.parent / "koinonia-db" / "seed"

CANARY = "CANARY-PRIVATE-CONTENT-7f3a9"

# Secret-like canary, assembled from parts (see module docstring).
# "CANARYSYNTHETIC" is 15 chars: tails are sized to each pattern's length.
_SECRET_SK = "sk-" + "CANARYSYNTHETIC" + "000000"
_SECRET_GHP = "ghp_" + "CANARYSYNTHETIC" + "0" * 21
_SECRET_AKIA = "AKIA" + "CANARYSYNTHETIC" + "0"
_SECRET_SK_ANT = "sk-ant-" + "CANARYSYNTHETIC" + "000000"

# Supported-format files at private-classified paths: admitted today, refused
# once classification-aware admission (plan step 2) lands. Each path matches
# a `private-never-in-git` inventory pattern but no name-based exclusion, so
# the inventory — not SKIP_DIRECTORIES — is what must refuse it.
PRIVATE_PATH_CASES = (
    "pkg.egg-info/notes.md",
    ".ruff_cache/notes.md",
    "docs-audit-ci.md",
    ".env.local.md",
)

PUBLIC_CONTROLS = (
    "notes.md",
    "docs/guide.md",
)


def _install_inventory(root: Path) -> None:
    """Copy the live classification inventory into a repo-shaped tmp root."""
    assert INVENTORY_SRC.exists(), f"live inventory missing: {INVENTORY_SRC}"
    dest = root / "docs" / "privacy-classification.yaml"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(INVENTORY_SRC, dest)


def test_ordinary_directory_canary_is_admitted(tmp_path: Path) -> None:
    """A canary in an ordinary directory is admitted — content alone does not classify.

    The #34 plan's step 1 expected this assertion to flip once step 2 landed.
    Live evidence corrects that expectation: the #33 inventory classifies
    paths, not content, and an ordinary `notes.md` matches the inventory's
    public `*.md` entry. Admission is path-classification only; a content
    policy is an owner decision recorded in ADR 004, not invented here. This
    test pins the boundary so the residual stays visible instead of silently
    flipping or silently passing.
    """
    root = tmp_path
    (root / "notes.md").write_text(
        f"# Notes\nThe draft mentions {CANARY} in passing.\n", encoding="utf-8"
    )
    rels = [str(p.relative_to(root)) for p in discover_documents(root)]
    assert rels == ["notes.md"]


@pytest.mark.parametrize("rel", PRIVATE_PATH_CASES)
def test_private_classified_path_is_refused(tmp_path: Path, rel: str) -> None:
    """A supported file at a private-classified path is refused at discovery.

    Fails before plan step 2 (the file is admitted) and passes after (the
    inventory's `private-never-in-git` patterns refuse it even though its
    name and extension are otherwise admissible).
    """
    _install_inventory(tmp_path)
    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"# Notes\nSynthetic canary {CANARY}.\n", encoding="utf-8")
    rels = [str(p.relative_to(tmp_path)) for p in discover_documents(tmp_path)]
    assert rel not in rels, f"private-classified path admitted: {rel}"


@pytest.mark.parametrize("rel", PUBLIC_CONTROLS)
def test_public_and_review_paths_stay_admitted(tmp_path: Path, rel: str) -> None:
    """Public paths (and `review` paths) are not over-blocked by step 2."""
    _install_inventory(tmp_path)
    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# Guide\nPublic text.\n", encoding="utf-8")
    rels = [str(p.relative_to(tmp_path)) for p in discover_documents(tmp_path)]
    assert rel in rels, f"public path refused: {rel}"


def test_review_paths_stay_admitted(tmp_path: Path) -> None:
    """A `review`-classified path stays admitted (ADR 003: keep, not move)."""
    _install_inventory(tmp_path)
    target = tmp_path / "docs" / "aiChatsThread" / "chat.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# Chat\nReview-class text.\n", encoding="utf-8")
    rels = [str(p.relative_to(tmp_path)) for p in discover_documents(tmp_path)]
    assert "docs/aiChatsThread/chat.md" in rels


@pytest.mark.parametrize(
    "secret",
    [_SECRET_SK, _SECRET_GHP, _SECRET_AKIA, _SECRET_SK_ANT],
)
def test_redact_secret_patterns_names_no_literal(secret: str) -> None:
    """Extracted text never echoes a credential-like value (issue acceptance).

    The redactor mirrors the four patterns the repo's secret-scan CI checks
    for, so a value CI would flag can never be echoed into an audit report.
    """
    from adaptive_personal_syllabus.docs_audit import redact_secret_patterns

    scrubbed = redact_secret_patterns(f"Add {secret} rotation to the runbook")
    assert secret not in scrubbed
    assert "[REDACTED]" in scrubbed
    assert redact_secret_patterns("Clean text without secrets.") == ("Clean text without secrets.")


def test_canary_stays_inside_admitted_store(tmp_path: Path) -> None:
    """Sweep: a planted canary lands in the admitted store and nowhere else.

    Ingest -> docs-audit -> export path. The generic canary sits in a plain
    paragraph (never extracted); the secret-like canary sits in an extracted
    suggestion line, so it reaches the audit report unless step 3 redacts it
    there. The report JSON/MD and the export JSON are the named outputs.
    """
    docs_root = tmp_path / "docs"
    docs_root.mkdir()
    _install_inventory(tmp_path)
    (docs_root / "notes.md").write_text(
        f"# Notes\nThe draft mentions {CANARY} in passing.\n", encoding="utf-8"
    )
    (docs_root / "plan.md").write_text(
        f"# Plan\n- Add {_SECRET_SK} rotation to the runbook.\n",
        encoding="utf-8",
    )

    storage = Storage(tmp_path / "audit.db")
    ledger = Ledger(storage)
    report = DocsAuditService(storage=storage, ledger=ledger).audit(
        root=docs_root,
        snapshot_name="canary-sweep",
    )

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    report_json = out_dir / "docs-audit-ci.json"
    report_md = out_dir / "docs-audit-ci.md"
    write_report(report_json, report)
    from adaptive_personal_syllabus.docs_audit import render_audit_markdown

    report_md.write_text(render_audit_markdown(report), encoding="utf-8")

    if SEED_DIR.exists():
        from adaptive_personal_syllabus.data_export import export_all

        export_all(seed_dir=SEED_DIR, output_dir=out_dir)
    else:
        pytest.skip("koinonia-db seed not present; export leg runs in CI")

    # The canary IS in the admitted store (the audit database chunks).
    chunks = storage.list_document_chunks(snapshot_id=report["snapshot"]["snapshot_id"])
    assert any(CANARY in chunk["text"] for chunk in chunks), "canary missing from store"
    assert any(_SECRET_SK in chunk["text"] for chunk in chunks), "secret canary missing"

    # ...and in no produced artifact outside the store.
    for path in sorted(out_dir.rglob("*")):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert CANARY not in text, f"generic canary leaked into {path.name}"
        assert _SECRET_SK not in text, f"secret canary leaked into {path.name}"

    # The extracted suggestion survives with the value redacted, not dropped.
    rendered = report_json.read_text(encoding="utf-8")
    assert "[REDACTED]" in rendered, "redaction marker missing from report"
    items = [
        item
        for item in report["suggestions"]["items"]
        if "rotation to the runbook" in item["text"]
    ]
    assert items, "extracted suggestion line lost entirely"
    assert _SECRET_SK not in json.dumps(report), "secret canary in report dict"


def test_sweep_reports_are_clean_without_seed(tmp_path: Path) -> None:
    """The audit-report leg of the sweep runs even when the seed is absent."""
    docs_root = tmp_path / "docs"
    docs_root.mkdir()
    (docs_root / "notes.md").write_text(
        f"# Notes\nThe draft mentions {CANARY} in passing.\n", encoding="utf-8"
    )
    (docs_root / "plan.md").write_text(
        f"# Plan\n- Add {_SECRET_SK} rotation to the runbook.\n",
        encoding="utf-8",
    )
    storage = Storage(tmp_path / "audit.db")
    ledger = Ledger(storage)
    report = DocsAuditService(storage=storage, ledger=ledger).audit(
        root=docs_root,
        snapshot_name="canary-sweep-noseed",
    )
    assert _SECRET_SK not in json.dumps(report)
    assert CANARY not in json.dumps(report)
