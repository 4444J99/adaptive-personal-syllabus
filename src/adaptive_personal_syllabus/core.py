"""Core module — CLI entry point for adaptive-personal-syllabus."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from . import __version__
from .corpus import CorpusIngestor
from .docs_audit import (
    DocsAuditService,
    build_milestone_execution_plan,
    render_audit_markdown,
    render_milestone_execution_markdown,
    write_report,
)
from .generator import SyllabusGenerator
from .hooks import HookRunner
from .ledger import Ledger
from .models import DifficultyLevel, LearnerProfile
from .planner import Planner
from .storage import DEFAULT_DB_PATH, DEFAULT_PROFILE_PATH, Storage


@click.group()
def cli() -> None:
    """Adaptive personal syllabus generator."""


@cli.command()
@click.option("--organs", required=True, help="Comma-separated organ codes (e.g., I,II,V)")
@click.option(
    "--level",
    type=click.Choice(["beginner", "intermediate", "advanced"]),
    default="beginner",
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
                "schema_version": "1.0",
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
    payload = {
        "schema_version": "1.0",
        "ok": ok,
        "event_count": event_count,
        "errors": errors,
    }
    click.echo(json.dumps(payload, indent=2))
    if not ok:
        raise click.ClickException("Ledger verification failed")


@cli.group()
def profile() -> None:
    """Learner profile commands."""


@profile.command("init")
@click.option("--name", required=True, help="Learner display name.")
@click.option("--organs", default="I", show_default=True, help="Comma-separated organ codes.")
@click.option(
    "--level",
    type=click.Choice(["beginner", "intermediate", "advanced"]),
    default="beginner",
    show_default=True,
)
@click.option("--goals", default="", help="Comma-separated goals.")
@click.option("--context", default="{}", help="JSON object with contextual metadata.")
@click.option("--completed", default="", help="Comma-separated completed module IDs.")
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
        "schema_version": "1.0",
        "name": name,
        "organs_of_interest": [o.strip() for o in organs.split(",") if o.strip()],
        "level": level,
        "goals": [g.strip() for g in goals.split(",") if g.strip()],
        "context": context_obj,
        "completed_modules": [c.strip() for c in completed.split(",") if c.strip()],
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

    click.echo(json.dumps({"schema_version": "1.0", "profile_path": str(output), "profile": profile_doc}, indent=2))


@cli.group()
def plan() -> None:
    """Plan generation commands."""


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
            lines.append("**Readings**")
            for reading in m["readings"]:
                lines.append(f"- {reading}")
            lines.append("")
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
def plan_generate(profile_path: Path, fmt: str, db_path: Path, seed_dir: Path | None) -> None:
    """Generate a profile-aware syllabus plan using ingested corpus evidence."""
    storage = Storage(db_path)
    chain = Ledger(storage)
    planner = Planner(storage=storage, ledger=chain, seed_dir=seed_dir)
    try:
        plan_doc = planner.generate(profile_path=profile_path)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    chain.append(
        "plan.export",
        {"plan_id": plan_doc["plan_id"], "db_plan_id": plan_doc["db_plan_id"], "format": fmt},
    )

    if fmt == "json":
        click.echo(json.dumps(plan_doc, indent=2))
    elif fmt == "md":
        click.echo(_render_plan_markdown(plan_doc))
    else:
        click.echo(_render_plan_text(plan_doc))


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
def chamber_run(hook_name: str, dry_run: bool, context: str, plan_id: int | None, db_path: Path) -> None:
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
        "schema_version": "1.0",
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
    db_path: Path,
) -> None:
    """Audit all docs files and map every suggestion/use-case to planned or implemented status."""
    root = root.expanduser().resolve()
    excluded_paths = _collect_excluded_paths(root, [write_json, write_md])

    storage = Storage(db_path)
    chain = Ledger(storage)
    auditor = DocsAuditService(storage=storage, ledger=chain)
    report = auditor.audit(root=root, snapshot_name=snapshot, exclude_paths=excluded_paths)
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
@click.option("--limit", type=int, default=20, show_default=True, help="Maximum prioritized items.")
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

    plan = build_milestone_execution_plan(report, milestone=selected_milestone, limit=max(1, limit))
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
