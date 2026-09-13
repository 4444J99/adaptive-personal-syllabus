"""Core module — CLI entry point for adaptive-personal-syllabus."""

from __future__ import annotations

import json
import os
import tempfile
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
from .planner import WINGS, Planner
from .storage import DEFAULT_DB_PATH, DEFAULT_PROFILE_PATH, Storage


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
        "schema_version": "1.0",
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
            {"schema_version": "1.0", "profile_path": str(output), "profile": profile_doc},
            indent=2,
        )
    )


@cli.group()
def plan() -> None:
    """Plan generation commands."""


def _render_assistant_example(encounter: dict[str, Any]) -> list[str]:
    lines = ["Assistant explanation: " + encounter["self_contained_example"]]
    if encounter.get("example_scope") == "independent_claim_inspection_not_topic_instruction":
        lines.append(
            "Scope: independent practice in inspecting a claim; "
            "topic-specific instruction remains unverified."
        )
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
def plan_generate(profile_path: Path, fmt: str, db_path: Path, seed_dir: Path | None) -> None:
    """Generate an optional learning plan with unverified corpus candidates."""
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


@plan.command("show")
@click.argument("plan_id", type=int)
@click.option("--db-path", type=click.Path(path_type=Path), default=str(DEFAULT_DB_PATH))
@click.option("--format", "fmt", type=click.Choice(["json", "text", "md"]), default="json")
def plan_show(plan_id: int, db_path: Path, fmt: str) -> None:
    """Retrieve an exact stored plan by database ID, including historical projections."""
    doc = Storage(db_path).get_plan(plan_id)
    if doc is None:
        raise click.ClickException("Plan not found")
    click.echo(
        json.dumps(doc, indent=2)
        if fmt == "json"
        else _render_plan_markdown(doc)
        if fmt == "md"
        else _render_plan_text(doc)
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
    click.echo("\n".join(lines))



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
@click.option("--db-path", type=click.Path(path_type=Path), default=str(DEFAULT_DB_PATH))
def plan_artifact(plan_id: int, wing: str, output: Path, db_path: Path) -> None:
    """Write an assistant-authored working sheet for one selected Wing; never publish."""
    import hashlib

    storage = Storage(db_path)
    doc = storage.get_plan(plan_id)
    if doc is None or wing not in doc.get("output_policy", {}).get("selected_wings", []):
        raise click.ClickException("Wing is not selected in this plan")
    lines = [
        f"# {wing} working sheet",
        "Assistant-authored scaffold; not learner-authored work.",
        "This is a local artifact. No publication is authorized.",
    ]
    for module in doc["modules"]:
        lines.extend(
            [
                "",
                "## " + module["title"],
                *module["encounter"]["steps"],
                *_render_assistant_example(module["encounter"]),
                "Learner words: [not supplied]",
                "Source support: unverified",
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


@corpus.command("passage")
@click.argument("document_id", type=int)
@click.argument("chunk_index", type=int)
@click.option("--db-path", type=click.Path(path_type=Path), default=str(DEFAULT_DB_PATH))
def corpus_passage(document_id: int, chunk_index: int, db_path: Path) -> None:
    """Display exact stored passage as data, never executable instructions."""
    passage = Storage(db_path).get_passage(document_id, chunk_index)
    if passage is None:
        raise click.ClickException("Unavailable or uninspected passage")
    click.echo(json.dumps(passage, indent=2))


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
@click.option("--db-path", type=click.Path(path_type=Path), default=str(DEFAULT_DB_PATH))
def corpus_support(
    document_id: int | None, snapshot_id: int | None, claim: str, db_path: Path
) -> None:
    """Inspect all judgments for an exact claim, retaining contradictions."""
    from .support import summarize_judgments

    if (document_id is None) == (snapshot_id is None):
        raise click.ClickException("Choose one document ID or --snapshot-id")
    click.echo(
        json.dumps(
            summarize_judgments(
                Storage(db_path).list_source_judgments(document_id, snapshot_id=snapshot_id),
                claim,
            ),
            indent=2,
        )
    )


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
