"""Deterministic docs-audit pipeline for ingest + suggestion/use-case tracking."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .corpus import TEXT_EXTENSIONS, CorpusIngestor, _read_admitted_bytes, discover_documents
from .ledger import Ledger
from .storage import Storage, utcnow_iso
from .versions import AUDIT_REPORT_SCHEMA_VERSION, MILESTONE_EXECUTION_PLAN_SCHEMA_VERSION

ACTIONABLE_MARKER = re.compile(r"actionable suggestions?\s*:?", re.IGNORECASE)
USE_CASE_PATTERN = re.compile(r"\buse[- ]cases?\b", re.IGNORECASE)
LEADING_ENUM_PATTERN = re.compile(r"^\s*(?:[-*•]\s+|\d+\.\s+)+")

# Credential-like patterns, mirroring .github/workflows/secret-scan.yml: a
# value CI would flag must never be echoed into a generated report (#34 step 3).
SECRET_PATTERNS = (
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),
    re.compile(r"ghp_[a-zA-Z0-9]{36}"),
    re.compile(r"AKIA[A-Z0-9]{16}"),
    re.compile(r"sk-ant-[a-zA-Z0-9]{20,}"),
)


def redact_secret_patterns(text: str) -> str:
    """Replace credential-like substrings with [REDACTED].

    Applied to extracted item text before it enters any report: the audit
    report echoes admitted file text outside the admitted store, so a
    credential-like value in an admitted file must not survive extraction.
    The suggestion itself is kept — only the value is redacted. The admitted
    store keeps the full text; only the report is scrubbed.
    """
    scrubbed = text
    for pattern in SECRET_PATTERNS:
        scrubbed = pattern.sub("[REDACTED]", scrubbed)
    return scrubbed


ACTION_VERB_PATTERN = re.compile(
    (
        r"^(add|align|annotate|benchmark|break|build|clarify|create|define|design|develop|"
        r"document|ensure|expand|guide|implement|improve|include|integrate|introduce|link|"
        r"map|offer|optimi[sz]e|phase|plan|position|prioritize|provide|quantify|reference|"
        r"set|simplify|specify|tier|track)\b"
    ),
    re.IGNORECASE,
)


IMPLEMENTED_CAPABILITY_RULES: list[tuple[str, tuple[str, ...]]] = [
    (
        "corpus.ingest-and-dedup",
        (
            "ingest",
            "dedup",
            "snapshot",
            "chunk",
            "json schema",
            "schema validation",
            "yaml",
            "toml",
            "csv",
            "tsv",
        ),
    ),
    (
        "ledger.hash-chain-and-provenance",
        (
            "ledger",
            "hash",
            "cryptographic",
            "chainblockark",
            "provenance",
            "prompt logging",
            "logging hooks",
        ),
    ),
    (
        "profile-and-plan-generation",
        (
            "learner profile",
            "profile",
            "personalization",
            "goals",
            "context",
            "wings",
            "artifact descriptors",
        ),
    ),
    (
        "cli-interfaces-and-json-exports",
        (
            "cli command",
            "json export",
            "markdown export",
            "corpus stats",
            "ledger verify",
            "profile init",
            "plan generate",
        ),
    ),
    (
        "chamber-hook-extension-points",
        (
            "aaw",
            "chamber",
            "hook",
            "character node",
            "self_as_mirror",
            "lg4",
        ),
    ),
]


MILESTONE_RULES: list[tuple[str, tuple[str, ...]]] = [
    (
        "pedagogy-scaffolding",
        (
            "quiz",
            "exercise",
            "rubric",
            "assessment",
            "tutorial",
            "scaffold",
            "prerequisite",
            "primer",
            "troubleshooting",
            "faq",
        ),
    ),
    (
        "systems-kernel-runtime",
        (
            "kernel",
            "bootloader",
            "scheduler",
            "filesystem",
            "memory",
            "interrupt",
            "qemu",
            "driver",
            "microkernel",
            "ebpf",
        ),
    ),
    (
        "dsl-neural-symbolic-verification",
        (
            "dsl",
            "antlr",
            "parser",
            "interpreter",
            "grammar",
            "meta-circular",
            "z3",
            "smt",
            "symbolic",
            "neural",
        ),
    ),
    (
        "ui-xr-accessibility",
        (
            "ui",
            "ux",
            "audio",
            "video",
            "aria",
            "a11y",
            "accessibility",
            "mobile",
            "ar",
            "vr",
            "xr",
            "screen-reader",
        ),
    ),
    (
        "integration-observability-ci",
        (
            "integration",
            "roadmap",
            "milestone",
            "benchmark",
            "performance",
            "kpi",
            "metric",
            "ci",
            "cicd",
            "workflow",
            "recovery",
            "feature prioritization",
        ),
    ),
    (
        "wings-community-governance",
        (
            "academic",
            "business",
            "social",
            "community",
            "wiki",
            "web/blog",
            "grants",
            "governance",
            "public scholarship",
            "building in public",
        ),
    ),
]


MILESTONE_IMPACT_WEIGHTS: dict[str, int] = {
    # Integration/CI has platform-wide leverage, so it is intentionally weighted highest.
    "integration-observability-ci": 10,
    "systems-kernel-runtime": 4,
    "pedagogy-scaffolding": 4,
    "ui-xr-accessibility": 3,
    "dsl-neural-symbolic-verification": 3,
    "wings-community-governance": 2,
    "general-backlog": 1,
}

MILESTONE_OBJECTIVES: dict[str, str] = {
    "integration-observability-ci": (
        "Establish measurable integration checkpoints, reliable CI quality gates, and "
        "quantitative KPI tracking for roadmap execution."
    ),
    "systems-kernel-runtime": "Advance kernel/runtime implementation safety and observability readiness.",
    "pedagogy-scaffolding": "Improve learning scaffolding via guided exercises, checkpoints, and diagnostics.",
    "ui-xr-accessibility": "Strengthen multi-modal UX quality, accessibility, and rendering performance coverage.",
    "dsl-neural-symbolic-verification": "Harden DSL and neural-symbolic tracks with reproducible validation paths.",
    "wings-community-governance": "Operationalize Wings/public scholarship/governance with measurable outputs.",
    "general-backlog": "Triage and route uncategorized actionables into concrete implementation milestones.",
}

MILESTONE_CHECKPOINTS: dict[str, list[str]] = {
    "integration-observability-ci": [
        "Checkpoint 1: Baseline KPI definitions and measurement schema committed.",
        "Checkpoint 2: CI validates docs audit ingestion completeness and test integrity.",
        "Checkpoint 3: Milestone tracker records implemented suggestion IDs with evidence links.",
    ],
}

EXECUTION_PRIORITY_HINTS: list[tuple[int, tuple[str, ...]]] = [
    (5, ("kpi", "metric", "benchmark", "reliability", "quantitative", "performance")),
    (4, ("ci", "cicd", "workflow", "checkpoint", "integration", "feature prioritization")),
    (3, ("dependency", "schema", "protocol", "recovery", "debug", "failure")),
]

STATUS_FILE_SUFFIXES = (".status.yaml", ".status.yml")

# Verification-record files: evidence that an item is implemented, never a
# discovery source (see _is_generated_output). One format only — a record
# lives in `implementation/milestones/*.verified.yaml`, never as an
# `evidence:` block inside a status yaml (#38 step 2).
VERIFIED_FILE_SUFFIXES = (".verified.yaml", ".verified.yml")

# Top-level report keys that vary run to run and carry no audit content.
# The drift gate compares reports with these dropped (#38 step 5).
DRIFT_COMPARISON_IGNORED_KEYS = ("generated_at", "root_path", "snapshot")


class DocsAuditError(ValueError):
    """A docs-audit claim file is broken: unknown ID or malformed evidence.

    Raised (fail-closed) instead of producing a report: a claim that names
    an item the audit cannot see, or evidence that is missing fields, is
    not a warning — the issue's "reject unknown IDs" rule (#38).
    """


@dataclass(frozen=True)
class VerificationRecord:
    """One verified implementation claim for one suggestion ID (#38 step 2).

    `head` is the merge commit on the target branch whose green checks are
    the evidence; `pr` is the delivering pull request; `checks` names the
    check runs (name + run id, each concluded success). The audit trusts
    the record only after the ancestry check passes — the record is a
    receipt, and the reviewer verifies the named checks at claim time.
    """

    suggestion_id: str
    milestone: str
    head: str
    pr: int
    checks: tuple[dict[str, Any], ...]
    source_path: str


@dataclass(frozen=True)
class ExtractedItem:
    text: str
    rel_path: str
    line: int


def _normalize_text(text: str) -> str:
    lowered = text.lower()
    lowered = re.sub(r"\*+", "", lowered)
    lowered = re.sub(r"\s+", " ", lowered).strip()
    lowered = re.sub(r"[^a-z0-9 ]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def _clean_text(text: str) -> str:
    cleaned = LEADING_ENUM_PATTERN.sub("", text.strip())
    cleaned = re.sub(r"\*\*", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .;:-")
    return cleaned.strip()


def _split_suggestion_blob(blob: str) -> list[str]:
    if not blob.strip():
        return []

    work = blob.replace("•", ";")
    work = ACTIONABLE_MARKER.sub("", work).strip()
    work = re.sub(r"\s+", " ", work)
    work = re.sub(r"\s+\d+\.\s+", " || ", f" {work} ").strip()
    work = work.replace(";", " || ")

    parts: list[str] = []
    for candidate in work.split("||"):
        cleaned = _clean_text(candidate)
        if cleaned:
            # Extracted text is report-bound: scrub credential-like values here
            # so no suggestion can carry one into the report (see #34 step 3).
            parts.append(redact_secret_patterns(cleaned))
    return parts


def _extract_items_from_text(text: str, rel_path: str) -> tuple[list[ExtractedItem], list[ExtractedItem]]:
    suggestions: list[ExtractedItem] = []
    use_cases: list[ExtractedItem] = []
    lines = text.splitlines()

    for i, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue

        if USE_CASE_PATTERN.search(stripped):
            cleaned_use_case = redact_secret_patterns(_clean_text(stripped))
            if cleaned_use_case:
                use_cases.append(ExtractedItem(cleaned_use_case, rel_path, i))

        marker_match = ACTIONABLE_MARKER.search(stripped)
        if marker_match:
            inline = stripped[marker_match.end():].strip(" :-")
            for text_item in _split_suggestion_blob(inline):
                suggestions.append(ExtractedItem(text_item, rel_path, i))

            lookahead = i
            while lookahead < len(lines):
                nxt_raw = lines[lookahead]
                nxt = nxt_raw.strip()
                if not nxt:
                    if suggestions:
                        break
                    lookahead += 1
                    continue
                if not re.match(r"^\s*(?:[-*•]|\d+\.)\s+", nxt_raw):
                    break
                for text_item in _split_suggestion_blob(nxt):
                    suggestions.append(ExtractedItem(text_item, rel_path, lookahead + 1))
                lookahead += 1
            continue

        if re.match(r"^\s*(?:[-*•]|\d+\.)\s+", line):
            bullet_text = redact_secret_patterns(_clean_text(stripped))
            if bullet_text and ACTION_VERB_PATTERN.search(bullet_text):
                suggestions.append(ExtractedItem(bullet_text, rel_path, i))

    return suggestions, use_cases


def _classify_suggestion(text: str) -> tuple[str, list[str], str | None]:
    lowered = text.lower()
    tags = [
        tag
        for tag, keywords in IMPLEMENTED_CAPABILITY_RULES
        if any(keyword in lowered for keyword in keywords)
    ]
    for milestone, keywords in MILESTONE_RULES:
        if any(keyword in lowered for keyword in keywords):
            return "planned", sorted(tags), milestone
    return "planned", sorted(tags), "general-backlog"


def _stable_item_id(prefix: str, text: str) -> str:
    digest = hashlib.sha256(_normalize_text(text).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _load_milestone_status_overrides(root: Path) -> dict[str, str]:
    """Load historical implementation claims, never verification evidence."""
    overrides: dict[str, str] = {}
    milestone_dir = root / "implementation" / "milestones"
    if not milestone_dir.exists():
        return overrides

    files = sorted(
        path
        for path in milestone_dir.iterdir()
        if path.is_file() and any(path.name.endswith(suffix) for suffix in STATUS_FILE_SUFFIXES)
    )
    for path in files:
        data = yaml.safe_load(_read_admitted_bytes(root, path).decode("utf-8")) or {}
        if not isinstance(data, dict):
            continue
        milestone = str(data.get("milestone", "")).strip()
        ids = data.get("implemented_suggestion_ids", [])
        if not milestone or not isinstance(ids, list):
            continue
        for item_id in ids:
            if isinstance(item_id, str) and item_id.strip():
                overrides[item_id.strip()] = milestone
    return overrides


_SHA40 = re.compile(r"^[0-9a-f]{40}$")


def _load_verification_records(
    root: Path, known_ids: set[str]
) -> list[VerificationRecord]:
    """Load `*.verified.yaml` evidence, fail-closed on broken records.

    Raises DocsAuditError when a file is malformed (missing fields, a head
    that is not a full SHA, a non-integer PR, empty checks, a check entry
    missing name/run id or concluded anything but success), when two
    records claim the same item, or when a record names an unknown ID.
    A record that passes this loader is well-formed; whether its head is
    live evidence is decided by the ancestry check in `audit`, which
    rejects stale heads with a reason instead of failing the run.
    """
    records: list[VerificationRecord] = []
    seen: dict[str, str] = {}
    milestone_dir = root / "implementation" / "milestones"
    if not milestone_dir.exists():
        return records

    files = sorted(
        path
        for path in milestone_dir.iterdir()
        if path.is_file() and any(path.name.endswith(suffix) for suffix in VERIFIED_FILE_SUFFIXES)
    )
    for path in files:
        rel = str(path.relative_to(root))
        data = yaml.safe_load(_read_admitted_bytes(root, path).decode("utf-8")) or {}
        if not isinstance(data, dict):
            raise DocsAuditError(f"{rel}: verification file is not a mapping")
        milestone = str(data.get("milestone", "")).strip()
        if not milestone:
            raise DocsAuditError(f"{rel}: verification file has no milestone")
        verifications = data.get("verifications")
        if not isinstance(verifications, list):
            raise DocsAuditError(f"{rel}: verification file has no verifications list")
        for entry in verifications:
            if not isinstance(entry, dict):
                raise DocsAuditError(f"{rel}: verification entry is not a mapping")
            suggestion_id = entry.get("suggestion_id")
            head = entry.get("head")
            pr = entry.get("pr")
            checks = entry.get("checks")
            if not isinstance(suggestion_id, str) or not suggestion_id.strip():
                raise DocsAuditError(f"{rel}: verification entry has no suggestion_id")
            suggestion_id = suggestion_id.strip()
            if not isinstance(head, str) or not _SHA40.match(head):
                raise DocsAuditError(
                    f"{rel}: verification for {suggestion_id} has no 40-hex head"
                )
            if isinstance(pr, bool) or not isinstance(pr, int):
                raise DocsAuditError(f"{rel}: verification for {suggestion_id} has no integer pr")
            if not isinstance(checks, list) or not checks:
                raise DocsAuditError(f"{rel}: verification for {suggestion_id} has no checks")
            clean_checks: list[dict[str, Any]] = []
            for check in checks:
                if not isinstance(check, dict):
                    raise DocsAuditError(
                        f"{rel}: verification for {suggestion_id} has a non-mapping check"
                    )
                name = check.get("name")
                run_id = check.get("run_id")
                conclusion = check.get("conclusion")
                if not isinstance(name, str) or not name.strip():
                    raise DocsAuditError(
                        f"{rel}: verification for {suggestion_id} has a check with no name"
                    )
                if isinstance(run_id, bool) or not isinstance(run_id, int):
                    raise DocsAuditError(
                        f"{rel}: verification for {suggestion_id} has a check with no integer run_id"
                    )
                if conclusion != "success":
                    raise DocsAuditError(
                        f"{rel}: verification for {suggestion_id} cites check {name!r} "
                        f"concluded {conclusion!r}, not success"
                    )
                clean_checks.append(
                    {"name": name.strip(), "run_id": run_id, "conclusion": conclusion}
                )
            if suggestion_id not in known_ids:
                raise DocsAuditError(
                    f"{rel}: verification names unknown suggestion {suggestion_id}"
                )
            if suggestion_id in seen:
                raise DocsAuditError(
                    f"{rel}: verification for {suggestion_id} duplicates {seen[suggestion_id]}"
                )
            seen[suggestion_id] = rel
            records.append(
                VerificationRecord(
                    suggestion_id=suggestion_id,
                    milestone=milestone,
                    head=head,
                    pr=pr,
                    checks=tuple(clean_checks),
                    source_path=rel,
                )
            )
    return records


def _resolve_audited_head(root: Path, audited_head: str | None) -> str | None:
    """The head the audit's evidence is checked against, or None.

    An explicit head must be a full SHA. Otherwise the current checkout's
    HEAD is used (git finds the enclosing repo from the docs root). None
    means the ancestry check cannot run and every record is rejected as
    unverifiable — never silently trusted.
    """
    if audited_head is not None:
        if not _SHA40.match(audited_head):
            raise DocsAuditError(f"audited head {audited_head!r} is not a full SHA")
        return audited_head
    git = shutil.which("git")
    if git is None:
        return None
    proc = subprocess.run(
        [git, "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True, text=True, timeout=30, check=False,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _record_head_is_ancestor(record_head: str, audited_head: str, root: Path) -> bool | None:
    """True when the record head is an ancestor of the audited head.

    False when git proves it is not (exit 1: stale head, or an unmerged
    PR's head). None when the check itself cannot run — the object is
    absent from this checkout (shallow clone, foreign head) or git failed
    — so the record is rejected as unverifiable rather than trusted.
    """
    git = shutil.which("git")
    if git is None:
        return None
    proc = subprocess.run(
        [git, "-C", str(root), "merge-base", "--is-ancestor", record_head, audited_head],
        capture_output=True, text=True, timeout=30, check=False,
    )
    if proc.returncode == 0:
        return True
    if proc.returncode == 1:
        return False
    return None


def _aggregate_items(
    items: list[ExtractedItem],
    prefix: str,
    *,
    status_overrides: dict[str, str] | None = None,
    verifications: dict[str, VerificationRecord] | None = None,
) -> list[dict[str, Any]]:
    """Aggregate extracted items into report rows.

    Status is `implemented` only for an item with a verified record (the
    record passed the loader and the ancestry check); keyword matches and
    status-yaml claims feed `implementation_claims` only and never promote.
    `implementation_tags` is derived from the verification record, never
    from keyword rules. `verification_status` is `verified` only with a
    valid record, otherwise `unverified`, never null.
    """
    grouped: dict[str, dict[str, Any]] = {}
    overrides = status_overrides or {}
    verified = verifications or {}
    for item in items:
        normalized = _normalize_text(item.text)
        if len(normalized) < 5:
            continue
        if normalized not in grouped:
            grouped[normalized] = {
                "id": _stable_item_id(prefix, item.text),
                "text": item.text,
                "source_refs": [],
            }
        grouped[normalized]["source_refs"].append({"rel_path": item.rel_path, "line": item.line})

    out: list[dict[str, Any]] = []
    for normalized, entry in grouped.items():
        refs = sorted(
            {(ref["rel_path"], ref["line"]) for ref in entry["source_refs"]},
            key=lambda pair: (pair[0], pair[1]),
        )
        collapsed_refs = [{"rel_path": rel_path, "line": line} for rel_path, line in refs]
        item_id = str(entry["id"])
        status, claims, milestone = _classify_suggestion(entry["text"])
        if prefix == "feat" and item_id in overrides:
            claims.append(f"milestone.{overrides[item_id]}")

        record = verified.get(item_id) if prefix == "feat" else None
        if record is not None:
            status = "implemented"
            tags = [f"milestone.{record.milestone}"]
            verification_status = "verified"
            verification: dict[str, Any] | None = {
                "head": record.head,
                "pr": record.pr,
                "milestone": record.milestone,
                "checks": [dict(check) for check in record.checks],
                "source_path": record.source_path,
            }
        else:
            tags = []
            verification_status = "unverified"
            verification = None

        out_item = {
            "id": item_id,
            "normalized_text": normalized,
            "text": entry["text"],
            "status": status,
            "implementation_tags": tags,
            "implementation_claims": claims,
            "verification_status": verification_status,
            "planned_milestone": milestone,
            "source_refs": collapsed_refs,
        }
        if verification is not None:
            out_item["verification"] = verification
        out.append(out_item)

    return sorted(out, key=lambda entry: (entry["status"], entry["text"].lower()))


def _path_sha256(path: Path, root: Path) -> str:
    return hashlib.sha256(_read_admitted_bytes(root, path)).hexdigest()


def _build_milestone_summary(suggestions: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str | None]:
    planned_counts: dict[str, int] = {}
    implemented_counts: dict[str, int] = {}
    milestone_keys = {milestone for milestone, _ in MILESTONE_RULES} | {"general-backlog"}

    for item in suggestions:
        if item["status"] == "planned":
            milestone = str(item["planned_milestone"] or "general-backlog")
            planned_counts[milestone] = planned_counts.get(milestone, 0) + 1
            milestone_keys.add(milestone)
        elif item["status"] == "implemented":
            for tag in item.get("implementation_tags", []):
                if tag.startswith("milestone."):
                    milestone = tag.split(".", maxsplit=1)[1]
                    implemented_counts[milestone] = implemented_counts.get(milestone, 0) + 1
                    milestone_keys.add(milestone)

    summary: list[dict[str, Any]] = []
    for milestone in sorted(milestone_keys):
        planned = planned_counts.get(milestone, 0)
        implemented = implemented_counts.get(milestone, 0)
        total = planned + implemented
        weight = MILESTONE_IMPACT_WEIGHTS.get(milestone, 1)
        summary.append(
            {
                "milestone_id": milestone,
                "planned_count": planned,
                "implemented_count": implemented,
                "total_count": total,
                "impact_weight": weight,
                "impact_score": planned * weight,
                "completion_pct": None,
                "objective": MILESTONE_OBJECTIVES.get(milestone, ""),
            }
        )

    summary.sort(key=lambda row: (-int(row["impact_score"]), -int(row["planned_count"]), row["milestone_id"]))
    recommended = next((row["milestone_id"] for row in summary if int(row["planned_count"]) > 0), None)
    return summary, recommended


def _milestone_item_priority(text: str) -> int:
    lowered = text.lower()
    score = 1
    for points, hints in EXECUTION_PRIORITY_HINTS:
        if any(hint in lowered for hint in hints):
            score += points
    return score


def build_milestone_execution_plan(
    report: dict[str, Any],
    *,
    milestone: str,
    limit: int = 20,
) -> dict[str, Any]:
    """Build deterministic prioritized execution plan for a milestone bucket."""
    planned = [
        item
        for item in report["suggestions"]["items"]
        if item["status"] == "planned" and (item["planned_milestone"] or "general-backlog") == milestone
    ]
    ranked = sorted(
        planned,
        key=lambda item: (-_milestone_item_priority(str(item["text"])), str(item["text"]).lower()),
    )
    selected = ranked[: max(1, limit)]

    selected_rows: list[dict[str, Any]] = []
    for item in selected:
        source = item["source_refs"][0]
        selected_rows.append(
            {
                "id": item["id"],
                "text": item["text"],
                "priority_score": _milestone_item_priority(str(item["text"])),
                "source_ref": {"rel_path": source["rel_path"], "line": source["line"]},
            }
        )

    return {
        "schema_version": MILESTONE_EXECUTION_PLAN_SCHEMA_VERSION,
        "artifact_kind": "generated-execution-plan",
        "generated_at": utcnow_iso(),
        "milestone": milestone,
        "objective": MILESTONE_OBJECTIVES.get(milestone, ""),
        "planned_item_count": len(planned),
        "selected_item_count": len(selected_rows),
        "checkpoints": MILESTONE_CHECKPOINTS.get(
            milestone,
            [
                "Checkpoint 1: Define scope and baseline metrics for this milestone.",
                "Checkpoint 2: Implement highest-priority roadmap items with tests.",
                "Checkpoint 3: Record completion evidence and rerun docs audit.",
            ],
        ),
        "exit_criteria": [
            "All selected milestone items are implemented or intentionally deferred with rationale.",
            "Automated tests pass on current branch.",
            "Docs audit report regenerated with updated milestone status evidence.",
        ],
        "selected_items": selected_rows,
    }


def render_milestone_execution_markdown(plan: dict[str, Any]) -> str:
    """Render markdown execution checklist for a milestone plan."""
    lines = [
        "<!-- aps-generated: discovery-output -->",
        f"# Milestone Execution Plan: {plan['milestone']}",
        "",
        f"- Generated at: `{plan['generated_at']}`",
        f"- Objective: {plan['objective'] or 'N/A'}",
        f"- Planned items in bucket: `{plan['planned_item_count']}`",
        f"- Selected for this run: `{plan['selected_item_count']}`",
        "",
        "## Checkpoints",
        "",
    ]
    for cp in plan["checkpoints"]:
        lines.append(f"- {cp}")

    lines.extend(["", "## Prioritized Items", ""])
    for item in plan["selected_items"]:
        src = item["source_ref"]
        lines.append(
            f"- `{item['id']}` (score={item['priority_score']}) {item['text']} "
            f"({src['rel_path']}:{src['line']})"
        )

    lines.extend(["", "## Exit Criteria", ""])
    for criterion in plan["exit_criteria"]:
        lines.append(f"- {criterion}")
    return "\n".join(lines) + "\n"


LEGACY_GENERATED_PATHS = {
    "implementation/docs-audit-report.json",
    "implementation/docs-audit-roadmap.md",
    "implementation/milestones/current-execution-plan.json",
    "implementation/milestones/current-execution-plan.md",
}


def _is_generated_output(rel_path: str, text: str) -> bool:
    """Keep generated artifacts as inventory, not discovery authority."""
    if rel_path in LEGACY_GENERATED_PATHS or text.startswith("<!-- aps-generated: discovery-output -->"):
        return True
    # Verification records are evidence about suggestions, never new
    # suggestions themselves (#38 step 6: a .verified.yaml is never
    # ingested as a suggestion source).
    if any(rel_path.endswith(suffix) for suffix in VERIFIED_FILE_SUFFIXES):
        return True
    if rel_path.endswith(".json"):
        try:
            data = json.loads(text)
        except ValueError:
            return False
        return isinstance(data, dict) and data.get("artifact_kind") in {
            "generated-docs-audit",
            "generated-docs-audit-reconciliation",
            "generated-execution-plan",
        }
    return False


# The audit's own two outputs, dropped from the drift-gate manifest
# comparison (see normalize_report_for_comparison): their hashes are
# inherently one regeneration behind on the CI path.
_DRIFT_SELF_OUTPUTS = {
    "implementation/docs-audit-report.json",
    "implementation/docs-audit-roadmap.md",
}


def normalize_report_for_comparison(report: dict[str, Any]) -> dict[str, Any]:
    """Drop run-varying metadata so a regenerated report can be compared.

    `generated_at` is always new, `root_path` depends on where the audit
    ran, and the `snapshot` block records the throwaway ingest database —
    none of them is audit content. The audit's own two outputs (the
    committed report and the roadmap markdown) are also dropped from the
    file manifest: when the report is regenerated with in-tree outputs
    (the commit path) the CLI excludes its write targets from discovery,
    and when regenerated with out-of-tree outputs (the CI path) they
    appear with hashes one regeneration behind — so their manifest entries
    can never match across the two paths. Every other file's manifest
    entry is still compared in full, and the ingest counts (redundant
    with the manifest length) are dropped with them; only
    `all_files_ingested` is kept. Anything else that differs means the
    committed report has drifted and the drift gate fails.
    """
    normalized = {
        key: value for key, value in report.items() if key not in DRIFT_COMPARISON_IGNORED_KEYS
    }
    normalized["files"] = [
        entry
        for entry in report.get("files", [])
        if entry.get("rel_path") not in _DRIFT_SELF_OUTPUTS
    ]
    verify = dict(report.get("ingest_verification", {}))
    verify.pop("expected_file_count", None)
    verify.pop("snapshot_doc_count", None)
    normalized["ingest_verification"] = verify
    return normalized


def reports_match(regenerated: dict[str, Any], committed: dict[str, Any]) -> bool:
    """True when a regenerated report reproduces the committed one."""
    return normalize_report_for_comparison(regenerated) == normalize_report_for_comparison(committed)


def report_difference_summary(regenerated: dict[str, Any], committed: dict[str, Any]) -> list[str]:
    """One line per top-level key where regenerated and committed differ."""
    left = normalize_report_for_comparison(regenerated)
    right = normalize_report_for_comparison(committed)
    lines: list[str] = []
    for key in sorted(set(left) | set(right)):
        if key not in left:
            lines.append(f"{key}: missing from regenerated report")
        elif key not in right:
            lines.append(f"{key}: missing from committed report")
        elif left[key] != right[key]:
            lines.append(f"{key}: regenerated != committed")
    return lines


class DocsAuditService:
    """Generate deterministic docs-audit reports from repository docs content."""

    def __init__(self, storage: Storage, ledger: Ledger) -> None:
        self.storage = storage
        self.ledger = ledger

    def audit(
        self,
        *,
        root: Path,
        snapshot_name: str,
        exclude_paths: set[Path] | None = None,
        display_root: Path | str | None = None,
        audited_head: str | None = None,
    ) -> dict[str, Any]:
        """Generate a docs-audit report.

        `display_root` names the audited tree as invoked (e.g. `docs`);
        when omitted the resolved path is recorded. The report's
        `root_path` is the invoked name, never an absolute machine path,
        so a committed report is reproducible from any checkout.
        `audited_head` is the head verification records are checked
        against; when omitted the enclosing checkout's HEAD is used.
        """
        # The invoked name, kept for the report; the resolved path drives
        # ingestion so relative roots work from any working directory.
        if display_root is not None:
            report_root = str(display_root).removeprefix("./")
        else:
            report_root = str(root.expanduser().resolve())
        root = root.expanduser().resolve()
        excluded = {p.expanduser().resolve() for p in (exclude_paths or set())}
        ingestor = CorpusIngestor(self.storage, self.ledger)
        snapshot = ingestor.ingest(root=root, snapshot_name=snapshot_name, exclude_paths=excluded)
        status_overrides = _load_milestone_status_overrides(root)

        paths = discover_documents(root, exclude_paths=excluded)
        file_manifest: list[dict[str, Any]] = []
        by_sha: dict[str, list[Path]] = {}
        for path in paths:
            sha = _path_sha256(path, root)
            by_sha.setdefault(sha, []).append(path)

        for sha, hash_paths in sorted(by_sha.items(), key=lambda pair: (pair[0], str(pair[1][0]))):
            canonical = min(hash_paths, key=lambda p: str(p.relative_to(root)))
            canonical_rel = str(canonical.relative_to(root))
            for path in sorted(hash_paths, key=lambda p: str(p.relative_to(root))):
                rel_path = str(path.relative_to(root))
                file_manifest.append(
                    {
                        "rel_path": rel_path,
                        "canonical_rel_path": canonical_rel,
                        "sha256": sha,
                        "size_bytes": path.stat().st_size,
                        "extension": path.suffix.lower(),
                        "is_duplicate_payload": rel_path != canonical_rel,
                    }
                )

        extracted_suggestions: list[ExtractedItem] = []
        extracted_use_cases: list[ExtractedItem] = []
        for sha in sorted(by_sha):
            canonical = min(by_sha[sha], key=lambda p: str(p.relative_to(root)))
            if canonical.suffix.lower() not in TEXT_EXTENSIONS:
                continue
            text = _read_admitted_bytes(root, canonical).decode("utf-8")
            rel_path = str(canonical.relative_to(root))
            if _is_generated_output(rel_path, text):
                continue
            suggestions, use_cases = _extract_items_from_text(text, rel_path)
            extracted_suggestions.extend(suggestions)
            extracted_use_cases.extend(use_cases)

        # Claims first, so the loader can reject unknown IDs against the
        # real item set: a status yaml naming an item the audit cannot see
        # is a broken claim, not a warning (#38 step 2).
        provisional = _aggregate_items(
            extracted_suggestions,
            prefix="feat",
            status_overrides=status_overrides,
        )
        known_ids = {item["id"] for item in provisional}
        unknown_claims = {
            key: value for key, value in status_overrides.items() if key not in known_ids
        }
        if unknown_claims:
            raise DocsAuditError(
                "status override names unknown suggestion(s): "
                + ", ".join(f"{key} ({value})" for key, value in sorted(unknown_claims.items()))
            )
        records = _load_verification_records(root, known_ids)
        head = _resolve_audited_head(root, audited_head)
        verified: dict[str, VerificationRecord] = {}
        rejected_verifications: list[dict[str, Any]] = []
        for record in records:
            if head is None:
                reason = "no-audited-head"
            else:
                ancestry = _record_head_is_ancestor(record.head, head, root)
                if ancestry is True:
                    verified[record.suggestion_id] = record
                    continue
                reason = "stale-head" if ancestry is False else "unverifiable-head"
            rejected_verifications.append(
                {
                    "suggestion_id": record.suggestion_id,
                    "head": record.head,
                    "pr": record.pr,
                    "milestone": record.milestone,
                    "source_path": record.source_path,
                    "reason": reason,
                }
            )

        aggregated_suggestions = _aggregate_items(
            extracted_suggestions,
            prefix="feat",
            status_overrides=status_overrides,
            verifications=verified,
        )
        aggregated_use_cases = _aggregate_items(extracted_use_cases, prefix="usecase")
        milestone_summary, recommended_start = _build_milestone_summary(aggregated_suggestions)

        implemented_count = sum(1 for item in aggregated_suggestions if item["status"] == "implemented")
        planned_count = sum(1 for item in aggregated_suggestions if item["status"] == "planned")

        snapshot_stats = self.storage.corpus_stats(snapshot_id=snapshot.snapshot_id)
        all_files_ingested = int(snapshot_stats["snapshot"]["doc_count"]) == len(file_manifest)

        report = {
            "schema_version": AUDIT_REPORT_SCHEMA_VERSION,
            "artifact_kind": "generated-docs-audit",
            "verification_status": "unverified",
            "unmatched_implementation_claims": {},
            "rejected_verifications": sorted(
                rejected_verifications, key=lambda row: row["suggestion_id"]
            ),
            "generated_at": utcnow_iso(),
            "root_path": report_root,
            "snapshot": {
                "snapshot_id": snapshot.snapshot_id,
                "snapshot_name": snapshot.snapshot_name,
                "doc_count": snapshot.doc_count,
                "unique_payload_count": snapshot.unique_payload_count,
                "created_at": snapshot.created_at,
            },
            "ingest_verification": {
                "expected_file_count": len(file_manifest),
                "snapshot_doc_count": int(snapshot_stats["snapshot"]["doc_count"]),
                "all_files_ingested": all_files_ingested,
            },
            "files": sorted(file_manifest, key=lambda item: item["rel_path"]),
            "suggestions": {
                "count": len(aggregated_suggestions),
                "implemented_count": implemented_count,
                "planned_count": planned_count,
                "items": aggregated_suggestions,
            },
            "use_cases": {
                "count": len(aggregated_use_cases),
                "items": aggregated_use_cases,
            },
            "milestones": {
                "summary": milestone_summary,
                "recommended_start_milestone": recommended_start,
            },
        }

        self.ledger.append(
            "docs.audit",
            {
                "root_path": str(root),
                "snapshot_id": snapshot.snapshot_id,
                "snapshot_name": snapshot.snapshot_name,
                "file_count": len(file_manifest),
                "suggestion_count": len(aggregated_suggestions),
                "implemented_count": implemented_count,
                "planned_count": planned_count,
                "use_case_count": len(aggregated_use_cases),
                "recommended_start_milestone": recommended_start,
            },
        )
        return report


def render_audit_markdown(report: dict[str, Any]) -> str:
    """Render a concise markdown roadmap for suggestions and use-cases."""
    snapshot = report["snapshot"]
    verify = report["ingest_verification"]
    suggestion_items = report["suggestions"]["items"]

    lines = [
        "<!-- aps-generated: discovery-output -->",
        "# Docs Audit Report",
        "Discovery only: implementation is unverified; zero verified items is not zero progress.",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Root: `{report['root_path']}`",
        f"- Snapshot: `{snapshot['snapshot_name']}` (id={snapshot['snapshot_id']})",
        f"- Files discovered: `{verify['expected_file_count']}`",
        f"- Files ingested: `{verify['snapshot_doc_count']}`",
        f"- Ingest complete: `{verify['all_files_ingested']}`",
        "",
        "## Suggestions Summary",
        "",
        f"- Total suggestions: `{report['suggestions']['count']}`",
        f"- Implemented: `{report['suggestions']['implemented_count']}`",
        f"- Planned: `{report['suggestions']['planned_count']}`",
        f"- Recommended start milestone: `{report['milestones']['recommended_start_milestone']}`",
        "",
        "## Milestone Ranking",
        "",
    ]

    for row in report["milestones"]["summary"]:
        lines.append(
            f"- `{row['milestone_id']}` impact={row['impact_score']} "
            f"(planned={row['planned_count']}, implemented={row['implemented_count']}, "
            "completion=unverified)"
        )

    lines.extend(["", "## Planned Milestones", ""])

    by_milestone: dict[str, list[dict[str, Any]]] = {}
    for item in suggestion_items:
        if item["status"] != "planned":
            continue
        milestone = item["planned_milestone"] or "general-backlog"
        by_milestone.setdefault(milestone, []).append(item)

    if not by_milestone:
        lines.append("- None")
    else:
        for milestone in sorted(by_milestone):
            lines.append(f"### {milestone}")
            for item in sorted(by_milestone[milestone], key=lambda entry: entry["text"].lower()):
                source = item["source_refs"][0]
                lines.append(f"- `{item['id']}` {item['text']} ({source['rel_path']}:{source['line']})")
            lines.append("")

    lines.extend(["## Implemented Coverage", ""])

    implemented = [item for item in suggestion_items if item["status"] == "implemented"]
    if not implemented:
        lines.append("- None")
    else:
        for item in sorted(implemented, key=lambda entry: entry["text"].lower()):
            tags = ", ".join(item["implementation_tags"]) or "n/a"
            source = item["source_refs"][0]
            lines.append(f"- `{item['id']}` {item['text']} [{tags}] ({source['rel_path']}:{source['line']})")

    lines.extend(
        [
            "",
            "## Use-Cases",
            "",
            f"- Total use-case mentions: `{report['use_cases']['count']}`",
        ]
    )

    for item in report["use_cases"]["items"]:
        source = item["source_refs"][0]
        lines.append(f"- `{item['id']}` {item['text']} ({source['rel_path']}:{source['line']})")

    return "\n".join(lines) + "\n"


def write_report(path: Path, content: str | dict[str, Any]) -> None:
    """Write markdown or JSON report content to disk."""
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    if isinstance(content, str):
        path.write_text(content, encoding="utf-8")
        return
    path.write_text(json.dumps(content, indent=2), encoding="utf-8")
