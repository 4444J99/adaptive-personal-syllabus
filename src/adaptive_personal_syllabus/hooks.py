"""Chamber hook interfaces and default no-op hook registry."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from .ledger import Ledger
from .models import ChamberHookSpec, CharacterNodeSpec
from .storage import Storage


@dataclass
class HookResult:
    """Result produced by a chamber hook execution."""

    hook_name: str
    status: str
    message: str
    output: dict[str, Any]


LedgerWriter = Callable[[str, dict[str, Any]], Any]


class ChamberHook(Protocol):
    """Protocol for chamber hook implementations."""

    spec: ChamberHookSpec

    def run(self, context: dict[str, Any], ledger_writer: LedgerWriter) -> HookResult:
        """Execute hook against the provided context."""


class NoOpChamberHook:
    """Default hook implementation used for MVP extension points."""

    def __init__(self, spec: ChamberHookSpec) -> None:
        self.spec = spec

    def run(self, context: dict[str, Any], ledger_writer: LedgerWriter) -> HookResult:
        payload = {
            "hook": self.spec.name,
            "stage": self.spec.stage,
            "context": context,
            "mode": "dry-run" if context.get("dry_run", True) else "execute",
        }
        ledger_writer("hook.execute", payload)
        return HookResult(
            hook_name=self.spec.name,
            status="ok",
            message=f"Hook '{self.spec.name}' executed as no-op.",
            output={
                "spec": {
                    "name": self.spec.name,
                    "description": self.spec.description,
                    "stage": self.spec.stage,
                    "tags": self.spec.tags,
                },
                "context": context,
            },
        )


def default_character_nodes() -> list[CharacterNodeSpec]:
    """Character-node extension metadata for future subsystem adapters."""
    return [
        CharacterNodeSpec(name="forrest", role="probability", focus_area="forecasting and path selection"),
        CharacterNodeSpec(name="chris", role="chaos", focus_area="stress testing and anti-fragility"),
        CharacterNodeSpec(name="jessica", role="ux_money", focus_area="usability and economic framing"),
        CharacterNodeSpec(name="david", role="symbolic_synthesis", focus_area="mythic and narrative synthesis"),
    ]


def default_hook_specs() -> list[ChamberHookSpec]:
    """AAW-stage and character-node hooks registered by default."""
    specs = [
        ChamberHookSpec("input_ritual", "Collect and normalize ritual input.", "aaw", ["aaw", "ritual"]),
        ChamberHookSpec("raa_academic_loop", "Run recursive academic reflection loop.", "aaw", ["aaw", "analysis"]),
        ChamberHookSpec("emi_myth_interpretation", "Run mythic interpretation stage.", "aaw", ["aaw", "myth"]),
        ChamberHookSpec(
            "aa10_referential_crossmapping",
            "Cross-map references across recursive artifacts.",
            "aaw",
            ["aaw", "crossmap"],
        ),
        ChamberHookSpec("self_as_mirror", "Run self-reflection mirror stage.", "aaw", ["aaw", "reflection"]),
        ChamberHookSpec("lg4_translation", "Translate output into LG4 symbolic form.", "aaw", ["aaw", "translation"]),
        ChamberHookSpec("code_export_sct", "Export stage output to SCT code artifact.", "aaw", ["aaw", "export"]),
        ChamberHookSpec("recursion_engine_archive", "Archive recursion outputs into ledger.", "aaw", ["aaw", "archive"]),
    ]

    for node in default_character_nodes():
        specs.append(
            ChamberHookSpec(
                name=f"{node.name}_node",
                description=f"Character-node adapter for {node.name} ({node.focus_area}).",
                stage="character_node",
                tags=["character", node.role],
            )
        )
    return specs


def default_hooks() -> dict[str, ChamberHook]:
    """Construct default hook registry."""
    return {spec.name: NoOpChamberHook(spec) for spec in default_hook_specs()}


class HookRunner:
    """Run hooks and persist run metadata + ledger events."""

    def __init__(self, storage: Storage, ledger: Ledger, hooks: dict[str, ChamberHook] | None = None) -> None:
        self.storage = storage
        self.ledger = ledger
        self.hooks = hooks or default_hooks()

    def run(
        self,
        hook_name: str,
        context: dict[str, Any],
        *,
        dry_run: bool = True,
        plan_id: int | None = None,
    ) -> tuple[int, HookResult]:
        if hook_name not in self.hooks:
            raise ValueError(f"Unknown hook: {hook_name}")

        merged_context = dict(context)
        merged_context.setdefault("dry_run", dry_run)
        merged_context.setdefault("plan_id", plan_id)

        hook = self.hooks[hook_name]
        result = hook.run(merged_context, self.ledger.append)
        run_id = self.storage.insert_hook_run(
            plan_id=plan_id,
            hook_name=hook_name,
            status=result.status,
            output=result.output,
        )
        return run_id, result
