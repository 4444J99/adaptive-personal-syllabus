"""Core module — CLI entry point for adaptive-personal-syllabus."""

from __future__ import annotations

import json
import os
import tempfile
import textwrap
from pathlib import Path
from typing import Any

import click

from . import __version__
from .admission import (
    admission_for_document,
    validate_admission_record,
    validate_revocation_record,
)
from .corpus import CorpusIngestor, CorpusRefresher
from .docs_audit import (
    DocsAuditService,
    build_milestone_execution_plan,
    render_audit_markdown,
    render_milestone_execution_markdown,
    write_report,
)
from .encounter import complete_encounter
from .freshness import source_freshness
from .generator import SyllabusGenerator
from .hooks import HookRunner
from .ledger import Ledger
from .models import DifficultyLevel, LearnerProfile
from .operating import (
    OperatingError,
    backup_store,
    budget_record,
    delete_learner,
    open_store,
    operating_status,
    redact_plan_doc,
    restore_store,
)
from .planner import WINGS, Planner
from .storage import DEFAULT_DB_PATH, DEFAULT_PROFILE_PATH, Storage, utcnow_iso
from .versions import CLI_ENVELOPE_SCHEMA_VERSION, PROFILE_SCHEMA_VERSION


@click.group()
def cli() -> None:
    """Adaptive personal syllabus generator."""


@cli.command()
@click.option("--organs", required=True, help="Comma-separated organ codes (e.g., I,II,V)")
@click.option(
    "--level",
    type=click.Choice(["unassessed", "beginner", "intermediate", "advanced"]),
    default="unassessed",
)
@click.option("--name", default="Learner", help="Learner name")
@click.option("--format", "fmt", type=click.Choice(["text", "json", "md"]), default="text")
def generate(organs: str, level: str, name: str, fmt: str) -> None:
    """Generate a personalized learning path."""
    organ_list = [o.strip() for o in organs.split(",")]
    profile = LearnerProfile(
        name=name,
        organs_of_interest=organ_list,
        level=DifficultyLevel(level),
    )
    generator = SyllabusGenerator()
    path = generator.generate(profile)

    if fmt == "json":
        data = {
            "path_id": path.path_id,
            "title": path.title,
            "total_hours": path.total_hours,
            "modules": [
                {
                    "module_id": m.module_id,
                    "title": m.title,
                    "organ": m.organ,
                    "difficulty": m.difficulty.value,
                    "readings": m.readings,
                    "questions": m.questions,
                    "estimated_hours": m.estimated_hours,
                }
                for m in path.modules
            ],
        }
        click.echo(json.dumps(data, indent=2))
    elif fmt == "md":
        click.echo(f"# {path.title}\n")
        click.echo(f"**Learner:** {path.learner.name}  ")
        click.echo(f"**Level:** {path.learner.level.value}  ")
        click.echo(f"**Total hours:** {path.total_hours}  ")
        click.echo(f"**Modules:** {path.module_count}\n")
        for i, m in enumerate(path.modules, 1):
            click.echo(f"## {i}. {m.title}")
            click.echo(f"*{m.organ} | {m.difficulty.value} | ~{m.estimated_hours}h*\n")
            if m.readings:
                click.echo("**Readings:**")
                for r in m.readings:
                    click.echo(f"- {r}")
                click.echo()
            if m.questions:
                click.echo("**Questions:**")
                for q in m.questions:
                    click.echo(f"1. {q}")
                click.echo()
    else:
        click.echo(f"Learning Path: {path.title}")
        click.echo(f"Total: {path.module_count} modules, ~{path.total_hours}h\n")
        for i, m in enumerate(path.modules, 1):
            click.echo(
                f"  {i}. [{m.difficulty.value[:3]}] {m.title} ({m.organ}, ~{m.estimated_hours}h)"
            )


@cli.command()
def version() -> None:
    """Show version."""
    click.echo(f"adaptive-personal-syllabus v{__version__}")


@cli.group()
def corpus() -> None:
    """Corpus ingestion and statistics commands."""


@corpus.command("ingest")
@click.option(
    "--root",
    required=True,
    type=click.Path(path_type=Path, exists=True, file_okay=False, dir_okay=True),
    help="Root directory to ingest.",
)
@click.option("--snapshot", required=True, help="Snapshot name for this ingest run.")
@click.option(
    "--db-path",
    type=click.Path(path_type=Path),
    default=str(DEFAULT_DB_PATH),
    show_default=True,
)
def corpus_ingest(root: Path, snapshot: str, db_path: Path) -> None:
    """Ingest document corpus with deterministic deduplication."""
    storage = Storage(db_path)
    chain = Ledger(storage)
    ingestor = CorpusIngestor(storage, chain)
    snap = ingestor.ingest(root=root, snapshot_name=snapshot)

    click.echo(
        json.dumps(
            {
                "schema_version": CLI_ENVELOPE_SCHEMA_VERSION,
                "snapshot": {
                    "snapshot_id": snap.snapshot_id,
                    "snapshot_name": snap.snapshot_name,
                    "root_path": snap.root_path,
                    "doc_count": snap.doc_count,
                    "unique_payload_count": snap.unique_payload_count,
                    "created_at": snap.created_at,
                },
            },
            indent=2,
        )
    )


@corpus.command("refresh")
@click.option(
    "--root",
    required=True,
    type=click.Path(path_type=Path, exists=True, file_okay=False, dir_okay=True),
    help="Root directory to re-read (the first source: the local ingest root).",
)
@click.option(
    "--max-age-hours",
    type=int,
    default=None,
    help="Per-source freshness bound in hours for the sources this run touches "
    "(new sources default to 168).",
)
@click.option(
    "--db-path",
    type=click.Path(path_type=Path),
    default=str(DEFAULT_DB_PATH),
    show_default=True,
)
def corpus_refresh(root: Path, max_age_hours: int | None, db_path: Path) -> None:
    """Re-read live sources and record one outcome per source.

    Operator-triggered; a scheduled invocation is the scheduled form.
    A refresh records versions and outcomes — it never creates a snapshot
    or rewrites stored documents. See docs/implementation/live-source-refresh.md.
    """
    storage = Storage(db_path)
    chain = Ledger(storage)
    refresher = CorpusRefresher(storage, chain)
    summary = refresher.refresh(root=root, max_age_hours=max_age_hours)
    click.echo(json.dumps(summary, indent=2))


@corpus.command("stats")
@click.option("--snapshot-id", type=int, default=None, help="Optional snapshot id selector.")
@click.option(
    "--snapshot-name",
    default="latest",
    show_default=True,
    help="Optional snapshot name selector (latest by default).",
)
@click.option(
    "--db-path",
    type=click.Path(path_type=Path),
    default=str(DEFAULT_DB_PATH),
    show_default=True,
)
def corpus_stats(snapshot_id: int | None, snapshot_name: str, db_path: Path) -> None:
    """Show stable JSON schema for corpus statistics."""
    if snapshot_id is not None and snapshot_name != "latest":
        raise click.ClickException("Use either --snapshot-id or --snapshot-name, not both")
    storage = Storage(db_path)
    click.echo(
        json.dumps(
            storage.corpus_stats(snapshot_id=snapshot_id, snapshot_name=snapshot_name),
            indent=2,
        )
    )


@cli.group("ledger")
def ledger_group() -> None:
    """Ledger operations."""


@ledger_group.command("verify")
@click.option(
    "--db-path",
    type=click.Path(path_type=Path),
    default=str(DEFAULT_DB_PATH),
    show_default=True,
)
def ledger_verify(db_path: Path) -> None:
    """Verify append-only ledger integrity."""
    storage = Storage(db_path)
    chain = Ledger(storage)
    ok, errors, event_count = chain.verify_chain()
    checkpoint = storage.latest_ledger_checkpoint()
    if checkpoint is None:
        checkpoint_payload: dict[str, object] = {"status": "absent"}
    else:
        # Only errors the checkpoint comparison itself raised name it;
        # a tamper/malformed error elsewhere leaves the checkpoint match.
        status = "mismatch" if any("checkpoint" in err for err in errors) else "match"
        checkpoint_payload = {
            "status": status,
            "event_count": int(checkpoint["event_count"]),
            "head_hash": str(checkpoint["head_hash"]),
        }
    payload = {
        "schema_version": CLI_ENVELOPE_SCHEMA_VERSION,
        "ok": ok,
        "event_count": event_count,
        "errors": errors,
        "error_categories": sorted({err.split(":", 1)[0] for err in errors}),
        "checkpoint": checkpoint_payload,
    }
    click.echo(json.dumps(payload, indent=2))
    if not ok:
        raise click.ClickException("Ledger verification failed")


@cli.group("ops")
def ops_group() -> None:
    """Operating evidence: backup, restore, deletion, status (#58, ADR 012)."""


@ops_group.command("backup")
@click.option(
    "--db-path",
    type=click.Path(path_type=Path),
    default=str(DEFAULT_DB_PATH),
    show_default=True,
)
@click.option(
    "--output",
    "output_path",
    required=True,
    type=click.Path(path_type=Path),
    help="Where to write the backup file.",
)
def ops_backup(db_path: Path, output_path: Path) -> None:
    """Copy the store to a named location with a checksum receipt."""
    try:
        receipt = backup_store(db_path, output_path)
    except OperatingError as exc:
        raise click.ClickException(str(exc)) from exc
    receipt["schema_version"] = CLI_ENVELOPE_SCHEMA_VERSION
    click.echo(json.dumps(receipt, indent=2))


@ops_group.command("restore")
@click.option(
    "--backup",
    "backup_path",
    required=True,
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    help="Backup file produced by `syllabus ops backup`.",
)
@click.option(
    "--db-path",
    type=click.Path(path_type=Path),
    default=str(DEFAULT_DB_PATH),
    show_default=True,
)
def ops_restore(backup_path: Path, db_path: Path) -> None:
    """Rebuild the store from a backup and verify it afterwards."""
    try:
        receipt = restore_store(backup_path, db_path)
    except OperatingError as exc:
        raise click.ClickException(str(exc)) from exc
    receipt["schema_version"] = CLI_ENVELOPE_SCHEMA_VERSION
    click.echo(json.dumps(receipt, indent=2))


@ops_group.command("delete-profile")
@click.argument("profile_id", type=int)
@click.option(
    "--db-path",
    type=click.Path(path_type=Path),
    default=str(DEFAULT_DB_PATH),
    show_default=True,
)
def ops_delete_profile(profile_id: int, db_path: Path) -> None:
    """Delete one learner profile and its dependent plans, with a receipt.

    The receipt carries counts only — no name, goals, or context. The
    profile file (if one was written by `profile init`) is the operator's
    to delete; see runbooks/deletion.md. The `profile.init` ledger event
    stays: the ledger is append-only (#52).
    """
    try:
        receipt = delete_learner(open_store(db_path), profile_id)
    except OperatingError as exc:
        raise click.ClickException(str(exc)) from exc
    receipt["schema_version"] = CLI_ENVELOPE_SCHEMA_VERSION
    click.echo(json.dumps(receipt, indent=2))


@ops_group.command("status")
@click.option(
    "--db-path",
    type=click.Path(path_type=Path),
    default=str(DEFAULT_DB_PATH),
    show_default=True,
)
@click.option(
    "--budget",
    "budget_path",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    default=None,
    help="Operating-budget artifact to read back (default: the ADR 012 values).",
)
def ops_status(db_path: Path, budget_path: Path | None) -> None:
    """Report the operating verdict: integrity, ledger, backup, freshness, budget.

    Exits non-zero when any check fails. The output carries no profile
    content by construction — counts and hashes only. A store SQLite
    cannot open at all still prints a failing payload instead of a bare
    error: the status command is the alert path, and an unreadable store
    is the alert firing, not a reason to stay silent.
    """
    try:
        storage = open_store(db_path)
    except OperatingError as exc:
        payload = {
            "schema_version": CLI_ENVELOPE_SCHEMA_VERSION,
            "ok": False,
            "checks": [
                {"name": "store_integrity", "status": "fail", "detail": str(exc)}
            ],
            "budget": budget_record(),
            "generated_at": utcnow_iso(),
        }
        click.echo(json.dumps(payload, indent=2))
        raise click.ClickException("Operating status failed") from exc
    try:
        payload = operating_status(storage, budget_path=budget_path)
    except OperatingError as exc:
        raise click.ClickException(str(exc)) from exc
    payload["schema_version"] = CLI_ENVELOPE_SCHEMA_VERSION
    click.echo(json.dumps(payload, indent=2))
    if not payload["ok"]:
        raise click.ClickException("Operating status failed")


@cli.group()
def profile() -> None:
    """Learner profile commands."""


@profile.command("init")
@click.option("--name", required=True, help="Learner display name.")
@click.option("--organs", default="I", show_default=True, help="Comma-separated organ codes.")
@click.option(
    "--level",
    type=click.Choice(["unassessed", "beginner", "intermediate", "advanced"]),
    default="unassessed",
    show_default=True,
)
@click.option("--goals", default="", help="Comma-separated goals.")
@click.option("--context", default="{}", help="JSON object with contextual metadata.")
@click.option("--completed", default="", help="Comma-separated completed module IDs.")
@click.option("--wing", "wings", multiple=True, type=click.Choice([w["wing_id"] for w in WINGS]))
@click.option(
    "--purpose",
    type=click.Choice(["understand", "practice", "evaluate", "enjoy"]),
    default="understand",
)
@click.option(
    "--medium",
    type=click.Choice(["written_or_spoken", "page", "audio", "practice", "mixed"]),
    default="written_or_spoken",
)
@click.option("--phone-only", is_flag=True)
@click.option(
    "--output",
    type=click.Path(path_type=Path),
    default=str(DEFAULT_PROFILE_PATH),
    show_default=True,
)
@click.option(
    "--db-path",
    type=click.Path(path_type=Path),
    default=str(DEFAULT_DB_PATH),
    show_default=True,
)
def profile_init(
    name: str,
    organs: str,
    level: str,
    goals: str,
    context: str,
    completed: str,
    wings: tuple[str, ...],
    purpose: str,
    medium: str,
    phone_only: bool,
    output: Path,
    db_path: Path,
) -> None:
    """Initialize a local learner profile file."""
    try:
        context_obj = json.loads(context)
    except json.JSONDecodeError as exc:
        raise click.ClickException("--context must be valid JSON") from exc

    if not isinstance(context_obj, dict):
        raise click.ClickException("--context must decode to a JSON object")

    profile_doc = {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "name": name,
        "organs_of_interest": [o.strip() for o in organs.split(",") if o.strip()],
        "level": level,
        "goals": [g.strip() for g in goals.split(",") if g.strip()],
        "context": context_obj,
        "completed_modules": [c.strip() for c in completed.split(",") if c.strip()],
        "learning_purpose": purpose,
        "medium": medium,
        "access_conditions": {"phone_only": phone_only},
        "output_policy": {"selected_wings": list(wings), "publication_authorized": False},
    }

    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(profile_doc, indent=2), encoding="utf-8")

    storage = Storage(db_path)
    chain = Ledger(storage)
    chain.append(
        "profile.init",
        {
            "profile_path": str(output),
            "name": name,
            "level": level,
            "organs_of_interest": profile_doc["organs_of_interest"],
        },
    )

    click.echo(
        json.dumps(
            {"schema_version": CLI_ENVELOPE_SCHEMA_VERSION, "profile_path": str(output), "profile": profile_doc},
            indent=2,
        )
    )


@cli.group()
def plan() -> None:
    """Plan generation commands."""


def _terminal_width(minimum: int = 20) -> int | None:
    """Live terminal width when stdout is a terminal, else None (ADR 010).

    The width comes from the terminal itself (``os.get_terminal_size``
    on stdout), never from the environment: the repo's public-surface
    contract (ADR 005, #42) forbids ``os.environ``/``getenv`` in src
    modules, and the tty reports the width directly. Piped output has
    no terminal width, so it keeps the historical unwrapped bytes,
    which the round-trip tests pin — the wrap is a display behavior for
    a known terminal, not a change to what the commands emit. The
    minimum keeps prose wrappable on very narrow terminals; below it no
    wrap width is useful.
    """
    try:
        columns = os.get_terminal_size(1).columns
    except OSError:
        return None
    return max(minimum, columns or 80)


def _wrap_terminal_lines(lines: list[str], width: int | None = None) -> list[str]:
    """Wrap learner-facing prose lines to the terminal width (ADR 010).

    Structural lines pass through unwrapped: blank lines, headings, and
    ``**...**`` metadata lines (which carry fingerprints that must not
    split across lines). List items wrap with a two-space continuation
    indent so markdown lists stay valid. Words are never split, so a
    line carrying a single unbreakable token (a fingerprint) stays whole
    on its own line even past the width. When no width is known (piped
    output), the lines pass through unchanged. JSON output
    never passes through here — it is machine output and stays unwrapped.
    """
    if width is None:
        width = _terminal_width()
    if width is None:
        return list(lines)
    wrapped: list[str] = []
    for line in lines:
        if not line or line.startswith(("#", "**")) or len(line) <= width:
            wrapped.append(line)
            continue
        if line.startswith("- "):
            wrapped.extend(
                textwrap.wrap(
                    line, width=width, subsequent_indent="  ",
                    break_long_words=False, break_on_hyphens=False,
                )
            )
        else:
            wrapped.extend(
                textwrap.wrap(
                    line, width=width, break_long_words=False, break_on_hyphens=False
                )
            )
    return wrapped


def _wrap_terminal_text(text: str, width: int | None = None) -> str:
    """Wrap learner-facing terminal text to the terminal width (ADR 010)."""
    return "\n".join(_wrap_terminal_lines(text.split("\n"), width))


def _render_assistant_example(encounter: dict[str, Any]) -> list[str]:
    lines = ["Assistant explanation: " + encounter["self_contained_example"]]
    if encounter.get("example_scope") == "independent_claim_inspection_not_topic_instruction":
        lines.append(
            "Scope: independent practice in inspecting a claim; "
            "topic-specific instruction remains unverified."
        )
    return lines


def _render_source_support(module: dict[str, Any]) -> list[str]:
    """Per-module source attribution: the live support status, never a hardcoded line.

    The module's ``source_selection`` (planner.py) carries the worst live
    judgment status for the module's selected sources, or
    ``source_support_unverified`` when no human-reviewed support is
    attached. A module without a ``source_selection`` (a historical plan)
    reports unverified rather than inventing support.
    """
    selection = module.get("source_selection") or {}
    status = str(selection.get("claim_support_status") or "source_support_unverified")
    lines = [f"Source support: {status}"]
    missing = selection.get("missing_support")
    if missing:
        lines.append(f"Source support note: {missing}")
    return lines


def _render_plan_text(plan_doc: dict[str, Any]) -> str:
    lines = [
        f"Plan: {plan_doc['title']} ({plan_doc['plan_id']})",
        f"Modules: {plan_doc['totals']['module_count']} | Hours: {plan_doc['totals']['total_hours']}",
        "",
    ]
    for m in plan_doc["modules"]:
        lines.append(
            f"{m['seq']}. [{m['difficulty'][:3]}] {m['title']} ({m['organ']}, ~{m['estimated_hours']}h)"
        )
        if "encounter" in m:
            lines.extend(m["encounter"]["steps"])
            lines.extend(_render_assistant_example(m["encounter"]))
            lines.append("Optional: written, spoken, explanation, or no response now.")
    return "\n".join(lines)


def _render_plan_markdown(plan_doc: dict[str, Any]) -> str:
    lines = [
        f"# {plan_doc['title']}",
        "",
        f"**Plan ID:** `{plan_doc['plan_id']}`  ",
        f"**DB Plan ID:** `{plan_doc['db_plan_id']}`  ",
        f"**Learner:** {plan_doc['profile']['name']}  ",
        f"**Level:** {plan_doc['profile']['level']}  ",
        f"**Modules:** {plan_doc['totals']['module_count']}  ",
        f"**Total Hours:** {plan_doc['totals']['total_hours']}  ",
        "",
    ]
    for m in plan_doc["modules"]:
        lines.append(f"## {m['seq']}. {m['title']}")
        lines.append("")
        lines.append(f"*{m['organ']} | {m['difficulty']} | ~{m['estimated_hours']}h*")
        lines.append("")
        if m["readings"]:
            lines.append("**Optional reading candidates**")
            for reading in m["readings"]:
                lines.append(f"- {reading}")
            lines.append("")
        if "encounter" in m:
            lines.append("**Assistant instruction**")
            lines.extend("- " + step for step in m["encounter"]["steps"])
            lines.extend(_render_assistant_example(m["encounter"]))
            lines.append("Optional: written, spoken, explanation, or no response now.")
    return "\n".join(lines)


@plan.command("generate")
@click.option(
    "--profile",
    "profile_path",
    required=True,
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
)
@click.option("--format", "fmt", type=click.Choice(["text", "json", "md"]), default="text")
@click.option(
    "--db-path",
    type=click.Path(path_type=Path),
    default=str(DEFAULT_DB_PATH),
    show_default=True,
)
@click.option(
    "--seed-dir",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
    default=None,
)
@click.option(
    "--slice-dir",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
    default=None,
    help="Domain-slice registry directory (defaults to the checkout's data/slices).",
)
@click.option(
    "--redacted",
    is_flag=True,
    help="Redact the learner name, goals, and context from the output (#58, ADR 012).",
)
def plan_generate(
    profile_path: Path,
    fmt: str,
    db_path: Path,
    seed_dir: Path | None,
    slice_dir: Path | None,
    redacted: bool,
) -> None:
    """Generate an optional learning plan with unverified corpus candidates."""
    storage = Storage(db_path)
    chain = Ledger(storage)
    planner = Planner(storage=storage, ledger=chain, seed_dir=seed_dir, slice_dir=slice_dir)
    try:
        plan_doc = planner.generate(profile_path=profile_path)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    chain.append(
        "plan.export",
        {"plan_id": plan_doc["plan_id"], "db_plan_id": plan_doc["db_plan_id"], "format": fmt},
    )

    # Redaction applies to the output copy only; the stored plan is
    # untouched, so a redacted view can never destroy the record it hides.
    if redacted:
        plan_doc = redact_plan_doc(plan_doc)

    if fmt == "json":
        click.echo(json.dumps(plan_doc, indent=2))
    elif fmt == "md":
        click.echo(_wrap_terminal_text(_render_plan_markdown(plan_doc)))
    else:
        click.echo(_wrap_terminal_text(_render_plan_text(plan_doc)))


@plan.command("show")
@click.argument("plan_id", type=int)
@click.option("--db-path", type=click.Path(path_type=Path), default=str(DEFAULT_DB_PATH))
@click.option("--format", "fmt", type=click.Choice(["json", "text", "md"]), default="json")
@click.option(
    "--redacted",
    is_flag=True,
    help="Redact the learner name, goals, and context from the output (#58, ADR 012).",
)
def plan_show(plan_id: int, db_path: Path, fmt: str, redacted: bool) -> None:
    """Retrieve an exact stored plan by database ID, including historical projections."""
    doc = Storage(db_path).get_plan(plan_id)
    if doc is None:
        raise click.ClickException("Plan not found")
    if redacted:
        doc = redact_plan_doc(doc)
    click.echo(
        json.dumps(doc, indent=2)
        if fmt == "json"
        else _wrap_terminal_text(_render_plan_markdown(doc))
        if fmt == "md"
        else _wrap_terminal_text(_render_plan_text(doc))
    )


@plan.command("encounter")
@click.argument("plan_id", type=int)
@click.option("--module-id", default=None, help="Choose a module; defaults to the first.")
@click.option(
    "--route",
    type=click.Choice(
        [
            "encounter",
            "short_written",
            "spoken_under_two_minutes",
            "worked_explanation",
            "no_response_now",
        ]
    ),
    default="encounter",
    show_default=True,
)
@click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text")
@click.option("--db-path", type=click.Path(path_type=Path), default=str(DEFAULT_DB_PATH))
def plan_encounter(
    plan_id: int, module_id: str | None, route: str, fmt: str, db_path: Path
) -> None:
    """View one optional encounter or explanation without recording learner performance."""
    doc = Storage(db_path).get_plan(plan_id)
    if doc is None:
        raise click.ClickException("Plan not found")
    modules = doc["modules"]
    module = next((m for m in modules if module_id is None or m["module_id"] == module_id), None)
    if module is None:
        raise click.ClickException("No matching module in this plan")
    encounter = module.get("encounter")
    if encounter is None:
        raise click.ClickException("This historical plan has no stored encounter")

    # Project once for both formats; never mutate the stored encounter.
    encounter = dict(encounter)
    prompts = {
        "encounter": "Optional: engage with this encounter in your own way.",
        "short_written": "Optional: write a short response in your own words.",
        "spoken_under_two_minutes": "Optional: speak in your own words for under two minutes.",
        "worked_explanation": "An explanation is available without assessment.",
        "no_response_now": "No response is required. You can return to this encounter later.",
    }
    if route in {"no_response_now", "worked_explanation"}:
        encounter["steps"] = []
    if route == "no_response_now":
        encounter["self_contained_example"] = ""
    payload = {
        "response_required": False,
        "response_prompt": prompts[route],
        "db_plan_id": plan_id,
        "module_id": module["module_id"],
        "title": module["title"],
        "view_route": route,
        "status": encounter["status"],
        "assessment_status": module["adaptation"]["assessment_status"],
        "performance_recorded": False,
        "publication_status": "not_published",
        "encounter": encounter,
    }
    if fmt == "json":
        click.echo(json.dumps(payload, indent=2))
        return

    lines = [
        module["title"],
        "Prepared material; no learner response or result is recorded.",
    ]
    if encounter["steps"]:
        lines.append("Assistant instruction:")
        lines.extend(encounter["steps"])
    if encounter["self_contained_example"]:
        lines.extend(_render_assistant_example(encounter))
    lines.append(payload["response_prompt"])
    lines.append(encounter["completion"])
    click.echo("\n".join(_wrap_terminal_lines(lines)))


@plan.command("encounter-complete")
@click.argument("plan_id", type=int)
@click.option("--module-id", default=None, help="Choose a module; defaults to the first.")
@click.option(
    "--response-route",
    required=True,
    type=click.Choice(
        [
            "short_written",
            "spoken_under_two_minutes",
            "worked_explanation",
            "no_response_now",
        ]
    ),
)
@click.option(
    "--learner-words",
    default=None,
    help="Verbatim learner text, recorded as supplied; omit for no response.",
)
@click.option("--db-path", type=click.Path(path_type=Path), default=str(DEFAULT_DB_PATH))
def plan_encounter_complete(
    plan_id: int,
    module_id: str | None,
    response_route: str,
    learner_words: str | None,
    db_path: Path,
) -> None:
    """Complete one encounter with an explicit response choice and append its receipt.

    Records the choice in the append-only ledger; it never assesses mastery.
    Unlike `plan encounter`, which is read-only, this command writes exactly
    one `encounter.receipt` ledger event.
    """
    storage = Storage(db_path)
    doc = storage.get_plan(plan_id)
    if doc is None:
        raise click.ClickException("Plan not found")
    modules = doc["modules"]
    module = next((m for m in modules if module_id is None or m["module_id"] == module_id), None)
    if module is None:
        raise click.ClickException("No matching module in this plan")
    encounter = module.get("encounter")
    if encounter is None:
        raise click.ClickException("This historical plan has no stored encounter")
    try:
        receipt = complete_encounter(
            module["adaptation"],
            encounter,
            {
                "module_id": module["module_id"],
                "response_route": response_route,
                "learner_words": learner_words,
            },
        )
    except (KeyError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    Ledger(storage).append("encounter.receipt", receipt)
    click.echo(json.dumps(receipt))



def _write_artifact_exclusive(output: Path, data: bytes) -> None:
    """Publish complete bytes atomically without replacing an existing path.

    The temporary file shares the output filesystem. A failed write/fsync/link
    leaves the requested output absent; hard-link creation fails on collisions.
    This does not make the separate ledger append a filesystem transaction.
    """
    fd, temporary = tempfile.mkstemp(prefix=".aps-artifact-", dir=output.parent)
    try:
        with os.fdopen(fd, "wb", buffering=0) as stream:
            remaining = memoryview(data)
            while remaining:
                written = os.write(stream.fileno(), remaining)
                if written <= 0:
                    raise OSError("Artifact write made no progress")
                remaining = remaining[written:]
            os.fsync(stream.fileno())
        os.link(temporary, output)
    finally:
        Path(temporary).unlink(missing_ok=True)


@plan.command("artifact")
@click.argument("plan_id", type=int)
@click.option("--wing", required=True, type=click.Choice([w["wing_id"] for w in WINGS]))
@click.option("--output", required=True, type=click.Path(path_type=Path))
@click.option(
    "--learner-words-file",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    default=None,
    help="File of learner-written prose to attach verbatim as a learner-authored section.",
)
@click.option("--db-path", type=click.Path(path_type=Path), default=str(DEFAULT_DB_PATH))
def plan_artifact(
    plan_id: int,
    wing: str,
    output: Path,
    learner_words_file: Path | None,
    db_path: Path,
) -> None:
    """Write an assistant-authored working sheet for one selected Wing; never publish."""
    import hashlib

    storage = Storage(db_path)
    doc = storage.get_plan(plan_id)
    if doc is None or wing not in doc.get("output_policy", {}).get("selected_wings", []):
        raise click.ClickException("Wing is not selected in this plan")
    learner_words_sha256 = None
    learner_words_text = None
    if learner_words_file is not None:
        try:
            learner_words_bytes = learner_words_file.read_bytes()
        except OSError as exc:
            raise click.ClickException(f"Cannot read learner words: {exc.strerror}") from exc
        if not learner_words_bytes:
            raise click.ClickException("Learner words file is empty")
        try:
            learner_words_text = learner_words_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise click.ClickException("Learner words must be UTF-8 text") from exc
        learner_words_sha256 = hashlib.sha256(learner_words_bytes).hexdigest()
    lines = [
        f"# {wing} working sheet",
        (
            "Attribution: assistant scaffold; source support stated per module; "
            "learner-authored text appears only in the learner section, when supplied."
        ),
        "This is a local artifact. No publication is authorized.",
    ]
    for module in doc["modules"]:
        lines.extend(
            [
                "",
                "## " + module["title"],
                *module["encounter"]["steps"],
                *_render_assistant_example(module["encounter"]),
                *_render_source_support(module),
            ]
        )
    if learner_words_text is not None:
        lines.extend(
            [
                "",
                "## Learner-authored prose",
                "Authorship: learner — words copied exactly as supplied, never rewritten.",
                "",
                learner_words_text,
            ]
        )
    data = ("\n".join(lines) + "\n").encode()
    try:
        _write_artifact_exclusive(output, data)
    except FileExistsError as exc:
        raise click.ClickException("Output already exists; choose a new version") from exc
    except OSError as exc:
        raise click.ClickException(
            f"Cannot write artifact to {output}: {exc.strerror}. "
            "Choose a writable file path in an existing directory."
        ) from exc
    receipt = {
        "plan_id": plan_id,
        "wing": wing,
        "path": str(output.resolve()),
        "sha256": hashlib.sha256(data).hexdigest(),
        "status": "generated_local",
        "publication_authorized": False,
        "learner_words_sha256": learner_words_sha256,
    }
    Ledger(storage).append("artifact.generate", receipt)
    click.echo(json.dumps(receipt))


@plan.command("authorize-publication")
@click.argument("artifact", type=click.Path(path_type=Path, exists=True, dir_okay=False))
@click.option("--destination", required=True)
@click.option(
    "--authorize", is_flag=True, required=True, help="Explicitly authorize these exact bytes."
)
@click.option("--db-path", type=click.Path(path_type=Path), default=str(DEFAULT_DB_PATH))
def authorize_publication(
    artifact: Path, destination: str, authorize: bool, db_path: Path
) -> None:
    """Record separate authorization for exact bytes and destination; performs no publication."""
    import hashlib

    if not destination.strip():
        raise click.ClickException("--destination must name the intended destination")
    try:
        data = artifact.read_bytes()
    except OSError as exc:
        raise click.ClickException(f"Cannot read artifact: {exc.strerror}") from exc
    receipt = {
        "artifact_sha256": hashlib.sha256(data).hexdigest(),
        "destination": destination,
        "publication_authorized": authorize,
        "publication_status": "not_published",
    }
    Ledger(Storage(db_path)).append("artifact.publication_authorization", receipt)
    click.echo(json.dumps(receipt))


def _latest_publication_decision(
    storage: Storage, artifact_sha256: str, destination: str
) -> tuple[str, dict[str, Any]] | None:
    """The latest ledger decision for exact bytes + destination, or None.

    Authorization and revocation are both decisions about the same pair;
    the latest event wins. Returns the event type and its payload, or
    None when no event names this pair. A malformed payload is skipped:
    the ledger chain verifier flags it separately, and it must not read
    as an authorization here.
    """
    latest: tuple[str, dict[str, Any]] | None = None
    for event in storage.iter_ledger_events():
        event_type = str(event.get("event_type"))
        if event_type not in (
            "artifact.publication_authorization",
            "artifact.publication_revocation",
        ):
            continue
        try:
            payload = json.loads(str(event.get("payload_json")))
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        if (
            payload.get("artifact_sha256") == artifact_sha256
            and payload.get("destination") == destination
        ):
            latest = (event_type, payload)
    return latest


@plan.command("revoke-publication")
@click.argument("artifact", type=click.Path(path_type=Path, exists=True, dir_okay=False))
@click.option("--destination", required=True)
@click.option("--reason", required=True, help="Why this authorization is revoked or denied.")
@click.option("--db-path", type=click.Path(path_type=Path), default=str(DEFAULT_DB_PATH))
def revoke_publication(
    artifact: Path, destination: str, reason: str, db_path: Path
) -> None:
    """Record a revocation (or denial) for exact bytes and destination; publishes nothing.

    The revocation is the latest decision for the pair, so `plan publish`
    refuses until a later authorization supersedes it. Recording a
    revocation before any authorization is a denial; after one, a revoke.
    """
    import hashlib

    if not destination.strip():
        raise click.ClickException("--destination must name the intended destination")
    if not reason.strip():
        raise click.ClickException("--reason must say why the authorization is revoked or denied")
    try:
        data = artifact.read_bytes()
    except OSError as exc:
        raise click.ClickException(f"Cannot read artifact: {exc.strerror}") from exc
    receipt = {
        "artifact_sha256": hashlib.sha256(data).hexdigest(),
        "destination": destination,
        "reason": reason,
        "publication_authorized": False,
        "publication_status": "not_published",
    }
    Ledger(Storage(db_path)).append("artifact.publication_revocation", receipt)
    click.echo(json.dumps(receipt))


@plan.command("publish")
@click.argument("artifact", type=click.Path(path_type=Path, exists=True, dir_okay=False))
@click.option(
    "--destination",
    required=True,
    help="Existing directory the authorized bytes are copied to.",
)
@click.option("--db-path", type=click.Path(path_type=Path), default=str(DEFAULT_DB_PATH))
def publish_artifact(artifact: Path, destination: str, db_path: Path) -> None:
    """Copy authorized artifact bytes to a destination; refuses without a live authorization.

    The latest ledger decision for the exact bytes and destination must be
    an authorization; a missing, denied, or revoked authorization refuses
    with no copy and no receipt. The copy is byte-for-byte the authorized
    file, written exclusively so it never overwrites an existing path.
    """
    import hashlib

    if not destination.strip():
        raise click.ClickException("--destination must name the intended destination")
    dest_dir = Path(destination)
    if not dest_dir.is_dir():
        raise click.ClickException("--destination must be an existing directory")
    try:
        data = artifact.read_bytes()
    except OSError as exc:
        raise click.ClickException(f"Cannot read artifact: {exc.strerror}") from exc
    artifact_sha256 = hashlib.sha256(data).hexdigest()
    storage = Storage(db_path)
    decision = _latest_publication_decision(storage, artifact_sha256, destination)
    if decision is None:
        raise click.ClickException(
            "No publication authorization for these exact bytes and destination"
        )
    event_type, payload = decision
    if event_type == "artifact.publication_revocation":
        reason = str(payload.get("reason") or "no reason recorded")
        raise click.ClickException(
            "Publication revoked for these exact bytes and destination: " + reason
        )
    if not payload.get("publication_authorized"):
        raise click.ClickException(
            "Publication denied for these exact bytes and destination"
        )
    target = dest_dir / artifact.name
    try:
        _write_artifact_exclusive(target, data)
    except FileExistsError as exc:
        raise click.ClickException(
            f"Publication already exists at {target}; publishing again would replace it"
        ) from exc
    except OSError as exc:
        raise click.ClickException(
            f"Cannot publish artifact to {target}: {exc.strerror}."
        ) from exc
    receipt = {
        "artifact_sha256": artifact_sha256,
        "destination": destination,
        "published_path": str(target.resolve()),
        "publication_status": "published",
    }
    Ledger(storage).append("artifact.publication", receipt)
    click.echo(json.dumps(receipt))


@corpus.command("passage")
@click.argument("document_id", type=int)
@click.argument("chunk_index", type=int)
@click.option("--db-path", type=click.Path(path_type=Path), default=str(DEFAULT_DB_PATH))
def corpus_passage(document_id: int, chunk_index: int, db_path: Path) -> None:
    """Display exact stored passage as data, never executable instructions."""
    storage = Storage(db_path)
    doc = storage.get_document(document_id)
    if doc is None:
        raise click.ClickException("Unavailable or uninspected passage")
    state = admission_for_document(storage, document_id)
    # Source admission (#48 step 7): a `private`-access source's paths
    # and contents never leave the store, whatever the command.
    if state["access"] == "private":
        raise click.ClickException("Private source: passage withheld")
    if state["content_kind"] in ("metadata_only", "extraction_failed"):
        # No passage text exists for this document; report the kind
        # instead of erroring on a missing chunk (#48 step 3).
        click.echo(
            json.dumps(
                {
                    "document_id": document_id,
                    "snapshot_id": int(doc["snapshot_id"]),
                    "sha256": str(doc["sha256"]),
                    "rel_path": str(doc["rel_path"]),
                    "content_kind": state["content_kind"],
                    "text": None,
                    "chunk_index": None,
                    "heading_path": None,
                    "aliases": [],
                    "document_completeness": state["content_kind"],
                    "admission_status": state["status"],
                },
                indent=2,
            )
        )
        return
    passage = storage.get_passage(document_id, chunk_index)
    if passage is None:
        raise click.ClickException("Unavailable or uninspected passage")
    passage["admission_status"] = state["status"]
    # Live-source refresh (#54): the passage carries its source's freshness
    # state, so a stale passage is never silently presented as current.
    snapshot = storage.get_snapshot(int(passage["snapshot_id"]))
    if snapshot is not None:
        passage["freshness"] = source_freshness(
            storage,
            root_path=str(snapshot["root_path"]),
            rel_path=str(passage["rel_path"]),
            document_sha256=str(passage["sha256"]),
        )
    click.echo(json.dumps(passage, indent=2))


@corpus.command("admit")
@click.argument("record_path", type=click.Path(path_type=Path, exists=True, dir_okay=False))
@click.option("--db-path", type=click.Path(path_type=Path), default=str(DEFAULT_DB_PATH))
def corpus_admit(record_path: Path, db_path: Path) -> None:
    """Record an attributed source-admission decision; never infer admission from retrieval.

    The record JSON carries document_id, the document row's exact sha256,
    owner, license, access (public/restricted/private), provenance,
    admitted_by, admission_basis, reviewer and reviewed_at — mirroring
    `corpus judge`'s attributed pattern. Admission binds to exact bytes:
    a sha mismatch is an error, never a silent carry-over.
    """
    storage = Storage(db_path)
    try:
        record = json.loads(record_path.read_text())
        if not isinstance(record, dict):
            raise ValueError("Admission record must be an object")  # noqa: TRY004
        normalized = validate_admission_record(storage, record)
        identifier = storage.record_source_admission(normalized)
    except (ValueError, KeyError, TypeError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps({"admission_id": identifier, "record": normalized}))


@corpus.command("revoke")
@click.argument("record_path", type=click.Path(path_type=Path, exists=True, dir_okay=False))
@click.option("--db-path", type=click.Path(path_type=Path), default=str(DEFAULT_DB_PATH))
def corpus_revoke(record_path: Path, db_path: Path) -> None:
    """Record an attributed revocation; revoked sources leave planner candidates and support.

    The record JSON carries document_id, the document row's exact sha256,
    revoked_by and revocation_reason (reviewed_at optional). A later admit
    re-admits the source; revocation is a decision, not a deletion.
    """
    storage = Storage(db_path)
    try:
        record = json.loads(record_path.read_text())
        if not isinstance(record, dict):
            raise ValueError("Revocation record must be an object")  # noqa: TRY004
        normalized = validate_revocation_record(storage, record)
        identifier = storage.record_source_admission(normalized)
    except (ValueError, KeyError, TypeError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps({"admission_id": identifier, "record": normalized}))


@corpus.command("judge")
@click.argument("record_path", type=click.Path(path_type=Path, exists=True, dir_okay=False))
@click.option(
    "--human-reviewed", is_flag=True, help="Attest that the named human inspected this passage."
)
@click.option("--db-path", type=click.Path(path_type=Path), default=str(DEFAULT_DB_PATH))
def corpus_judge(record_path: Path, human_reviewed: bool, db_path: Path) -> None:
    """Append an attributed claim judgment; never infer human review from retrieval."""
    try:
        record = json.loads(record_path.read_text())
        if not isinstance(record, dict):
            raise ValueError("Judgment must be an object")  # noqa: TRY004
        if record.get("reviewer_status") == "human_reviewed" and not human_reviewed:
            raise ValueError("Human review requires explicit --human-reviewed attestation")
        identifier = Storage(db_path).record_source_judgment(record)
    except (ValueError, KeyError, TypeError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps({"judgment_id": identifier, "record": record}))


@corpus.command("support")
@click.argument("document_id", type=click.IntRange(min=1), required=False)
@click.option(
    "--snapshot-id",
    type=click.IntRange(min=1),
    default=None,
    help="Inspect judgments across a snapshot.",
)
@click.option("--claim", required=True)
@click.option(
    "--revalidate",
    is_flag=True,
    help="Re-check stored judgments against the latest snapshot first, "
    "superseding those whose passage no longer verifies (#50 step 6).",
)
@click.option("--db-path", type=click.Path(path_type=Path), default=str(DEFAULT_DB_PATH))
def corpus_support(
    document_id: int | None,
    snapshot_id: int | None,
    claim: str,
    revalidate: bool,
    db_path: Path,
) -> None:
    """Inspect all judgments for an exact claim, retaining contradictions.

    A `private`-access source's judgments are withheld (document mode
    refuses; snapshot mode drops them and reports the count), and a
    revoked source leaves the support path entirely (#48 steps 4/7).
    Superseded judgments are listed separately and never count as live
    support (#50): they are history about old source text, not evidence
    about the current text.
    """
    from .support import summarize_judgments

    if (document_id is None) == (snapshot_id is None):
        raise click.ClickException("Choose one document ID or --snapshot-id")
    storage = Storage(db_path)
    revalidation: dict[str, Any] | None = None
    if revalidate:
        revalidation = storage.revalidate_judgments()
    private_documents_excluded = 0
    try:
        if document_id is not None:
            state = admission_for_document(storage, document_id)
            if state["access"] == "private":
                raise click.ClickException("Private source: support withheld")
            if state["status"] == "revoked":
                raise click.ClickException("Source revoked: support withheld")
        records = storage.list_source_judgments(document_id, snapshot_id=snapshot_id)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    if snapshot_id is not None:
        kept: list[dict[str, Any]] = []
        seen_private: set[int] = set()
        for record in records:
            state = admission_for_document(storage, int(record["document_id"]))
            if state["access"] == "private":
                if int(record["document_id"]) not in seen_private:
                    seen_private.add(int(record["document_id"]))
                    private_documents_excluded += 1
                continue
            kept.append(record)
        records = kept
    summary = summarize_judgments(records, claim)
    if snapshot_id is not None:
        summary["private_documents_excluded"] = private_documents_excluded
    if revalidation is not None:
        summary["revalidation"] = revalidation
    click.echo(json.dumps(summary, indent=2))


@cli.group()
def chamber() -> None:
    """Chamber hook orchestration commands."""


@chamber.command("run")
@click.option("--hook", "hook_name", required=True, help="Hook name to execute.")
@click.option("--dry-run/--execute", default=True, show_default=True)
@click.option("--context", default="{}", help="JSON object context for the hook.")
@click.option("--plan-id", type=int, default=None, help="Optional DB plan id.")
@click.option(
    "--db-path",
    type=click.Path(path_type=Path),
    default=str(DEFAULT_DB_PATH),
    show_default=True,
)
def chamber_run(
    hook_name: str, dry_run: bool, context: str, plan_id: int | None, db_path: Path
) -> None:
    """Run a registered chamber hook (no-op defaults in MVP1)."""
    try:
        context_obj = json.loads(context)
    except json.JSONDecodeError as exc:
        raise click.ClickException("--context must be valid JSON") from exc

    if not isinstance(context_obj, dict):
        raise click.ClickException("--context must decode to a JSON object")

    storage = Storage(db_path)
    chain = Ledger(storage)
    runner = HookRunner(storage=storage, ledger=chain)

    try:
        run_id, result = runner.run(
            hook_name=hook_name,
            context=context_obj,
            dry_run=dry_run,
            plan_id=plan_id,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    payload = {
        "schema_version": CLI_ENVELOPE_SCHEMA_VERSION,
        "run_id": run_id,
        "hook": result.hook_name,
        "status": result.status,
        "message": result.message,
        "output": result.output,
    }
    click.echo(json.dumps(payload, indent=2))


@cli.group("docs")
def docs_group() -> None:
    """Docs ingestion + suggestion coverage audits."""


def _collect_excluded_paths(root: Path, output_paths: list[Path | None]) -> set[Path]:
    root = root.expanduser().resolve()
    excluded_paths: set[Path] = set()
    for output_path in output_paths:
        if output_path is None:
            continue
        resolved = output_path.expanduser().resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        excluded_paths.add(resolved)
    return excluded_paths


@docs_group.command("audit")
@click.option(
    "--root",
    required=True,
    type=click.Path(path_type=Path, exists=True, file_okay=False, dir_okay=True),
    help="Root docs directory to audit.",
)
@click.option("--snapshot", default="docs-audit", show_default=True, help="Snapshot name.")
@click.option("--format", "fmt", type=click.Choice(["json", "md"]), default="json")
@click.option(
    "--write-json",
    type=click.Path(path_type=Path),
    default=None,
    help="Optional output path for JSON report.",
)
@click.option(
    "--write-md",
    type=click.Path(path_type=Path),
    default=None,
    help="Optional output path for Markdown roadmap.",
)
@click.option(
    "--audited-head",
    default=None,
    help="Head the verification records are checked against (full SHA). "
    "Defaults to the enclosing checkout's HEAD; without a checkout, "
    "records are rejected as unverifiable.",
)
@click.option(
    "--db-path",
    type=click.Path(path_type=Path),
    default=str(DEFAULT_DB_PATH),
    show_default=True,
)
def docs_audit(
    root: Path,
    snapshot: str,
    fmt: str,
    write_json: Path | None,
    write_md: Path | None,
    audited_head: str | None,
    db_path: Path,
) -> None:
    """Audit all docs files and map every suggestion/use-case to planned or implemented status."""
    raw_root = root
    root = root.expanduser().resolve()
    excluded_paths = _collect_excluded_paths(root, [write_json, write_md])

    storage = Storage(db_path)
    chain = Ledger(storage)
    auditor = DocsAuditService(storage=storage, ledger=chain)
    report = auditor.audit(
        root=root,
        snapshot_name=snapshot,
        exclude_paths=excluded_paths,
        display_root=raw_root,
        audited_head=audited_head,
    )
    markdown = render_audit_markdown(report)

    if write_json is not None:
        write_report(write_json, report)
    if write_md is not None:
        write_report(write_md, markdown)

    if fmt == "md":
        click.echo(markdown)
    else:
        click.echo(json.dumps(report, indent=2))


@docs_group.command("execute-milestone")
@click.option(
    "--root",
    required=True,
    type=click.Path(path_type=Path, exists=True, file_okay=False, dir_okay=True),
    help="Root docs directory to audit.",
)
@click.option("--snapshot", default="docs-audit", show_default=True, help="Snapshot name.")
@click.option(
    "--milestone",
    default=None,
    help="Milestone ID to execute (defaults to report-recommended start milestone).",
)
@click.option(
    "--limit", type=int, default=20, show_default=True, help="Maximum prioritized items."
)
@click.option("--format", "fmt", type=click.Choice(["json", "md"]), default="json")
@click.option(
    "--write-json",
    type=click.Path(path_type=Path),
    default=None,
    help="Optional output path for JSON execution plan.",
)
@click.option(
    "--write-md",
    type=click.Path(path_type=Path),
    default=None,
    help="Optional output path for Markdown execution plan.",
)
@click.option(
    "--db-path",
    type=click.Path(path_type=Path),
    default=str(DEFAULT_DB_PATH),
    show_default=True,
)
def docs_execute_milestone(
    root: Path,
    snapshot: str,
    milestone: str | None,
    limit: int,
    fmt: str,
    write_json: Path | None,
    write_md: Path | None,
    db_path: Path,
) -> None:
    """Build and export a prioritized implementation plan for one milestone bucket."""
    root = root.expanduser().resolve()
    excluded_paths = _collect_excluded_paths(root, [write_json, write_md])

    storage = Storage(db_path)
    chain = Ledger(storage)
    auditor = DocsAuditService(storage=storage, ledger=chain)
    report = auditor.audit(root=root, snapshot_name=snapshot, exclude_paths=excluded_paths)

    selected_milestone = milestone or report["milestones"]["recommended_start_milestone"]
    if not selected_milestone:
        raise click.ClickException("No planned milestone items found in audit report.")

    plan = build_milestone_execution_plan(
        report, milestone=selected_milestone, limit=max(1, limit)
    )
    markdown = render_milestone_execution_markdown(plan)

    if write_json is not None:
        write_report(write_json, plan)
    if write_md is not None:
        write_report(write_md, markdown)

    if fmt == "md":
        click.echo(markdown)
    else:
        click.echo(json.dumps(plan, indent=2))


def main() -> None:
    """Entry point."""
    cli()


if __name__ == "__main__":
    main()
