"""Append-only hash-chain ledger utilities."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from .models import LedgerEvent
from .storage import Storage, utcnow_iso


class Ledger:
    """ChainBlockARK-style append-only ledger with integrity checks."""

    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    @staticmethod
    def _hash_event(
        prev_hash: str,
        event_type: str,
        payload: dict[str, Any],
        created_at: str,
    ) -> str:
        blob = json.dumps(
            {
                "created_at": created_at,
                "event_type": event_type,
                "payload": payload,
                "prev_hash": prev_hash,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def append(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        conn: sqlite3.Connection | None = None,
    ) -> LedgerEvent:
        if conn is None:
            with self.storage.connection() as owned:
                return self.append(event_type, payload, conn=owned)
        prev_hash = self.storage.last_ledger_hash(conn=conn)
        created_at = utcnow_iso()
        event_hash = self._hash_event(prev_hash, event_type, payload, created_at)
        self.storage.append_ledger_event(
            prev_hash=prev_hash,
            event_hash=event_hash,
            event_type=event_type,
            payload=payload,
            created_at=created_at,
            conn=conn,
        )
        # The checkpoint records this append's chain head in the same
        # transaction, so it commits or rolls back with the event. A
        # checkpoint is a statement about the chain head, not history,
        # so only the latest is kept (see Storage.record_ledger_checkpoint).
        event_count = self.storage.ledger_event_count(conn=conn)
        self.storage.record_ledger_checkpoint(event_count, event_hash, conn=conn)
        return LedgerEvent(
            prev_hash=prev_hash,
            event_hash=event_hash,
            event_type=event_type,
            payload=payload,
            created_at=created_at,
        )

    def verify_chain(self) -> tuple[bool, list[str], int]:
        """Verify ledger hash linkage, per-event hashes, and checkpoints.

        Errors carry a category prefix (tamper / truncation / malformed /
        incomplete); existing callers match on the message text after the
        prefix. The checkpoint comparison is prefix-shaped: the chain must
        reach at least the checkpointed count, and the event at the
        checkpointed position must carry the checkpointed head hash. A
        longer chain is fine — later appends do not invalidate an earlier
        checkpoint — but a shorter chain is truncation and a rewritten
        prefix is tamper. The verifier never writes a checkpoint: a
        re-baseline here would launder a loss.
        """
        rows = self.storage.iter_ledger_events()
        errors: list[str] = []
        expected_prev = ""

        for row in rows:
            row_id = int(row["id"])
            row_prev = str(row["prev_hash"])
            row_type = str(row["event_type"])
            row_hash = str(row["event_hash"])
            row_created = str(row["created_at"])

            if row_prev != expected_prev:
                errors.append(
                    f"tamper: event {row_id}: prev_hash mismatch (expected {expected_prev or '<genesis>'}, got {row_prev or '<genesis>'})"
                )

            try:
                raw_payload = row["payload_json"]
                if raw_payload is None:
                    raise TypeError("payload_json is NULL")
                payload = json.loads(str(raw_payload))
                if not isinstance(payload, dict):
                    raise TypeError(f"expected JSON object, got {type(payload).__name__}")
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                errors.append(f"malformed: event {row_id}: malformed payload JSON ({exc})")
            else:
                computed_hash = self._hash_event(row_prev, row_type, payload, row_created)
                if computed_hash != row_hash:
                    errors.append(
                        f"tamper: event {row_id}: event_hash mismatch (expected {computed_hash}, got {row_hash})"
                    )

            expected_prev = row_hash

        checkpoint = self.storage.latest_ledger_checkpoint()
        if checkpoint is not None:
            expected_count = int(checkpoint["event_count"])
            expected_head = str(checkpoint["head_hash"])
            if expected_count > 0:
                if len(rows) < expected_count:
                    errors.append(
                        f"truncation: checkpoint expects {expected_count} events "
                        f"ending in {expected_head[:12]}..., found {len(rows)}"
                    )
                elif str(rows[expected_count - 1]["event_hash"]) != expected_head:
                    errors.append(
                        f"tamper: checkpoint head mismatch at event {expected_count} "
                        f"(expected {expected_head[:12]}..., "
                        f"got {str(rows[expected_count - 1]['event_hash'])[:12]}...)"
                    )

        for plan_id in self.storage.plans_missing_ledger_events():
            errors.append(
                f"incomplete: plan {plan_id} has no plan.generate ledger event"
            )

        return (len(errors) == 0, errors, len(rows))
