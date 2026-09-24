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
        return LedgerEvent(
            prev_hash=prev_hash,
            event_hash=event_hash,
            event_type=event_type,
            payload=payload,
            created_at=created_at,
        )

    def verify_chain(self) -> tuple[bool, list[str], int]:
        """Verify ledger hash linkage and per-event hashes."""
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
                    f"event {row_id}: prev_hash mismatch (expected {expected_prev or '<genesis>'}, got {row_prev or '<genesis>'})"
                )

            try:
                raw_payload = row["payload_json"]
                if raw_payload is None:
                    raise ValueError("payload_json is NULL")
                payload = json.loads(str(raw_payload))
                if not isinstance(payload, dict):
                    raise ValueError(f"expected JSON object, got {type(payload).__name__}")
            except Exception as exc:
                errors.append(f"event {row_id}: malformed payload JSON ({exc})")
            else:
                computed_hash = self._hash_event(row_prev, row_type, payload, row_created)
                if computed_hash != row_hash:
                    errors.append(
                        f"event {row_id}: event_hash mismatch (expected {computed_hash}, got {row_hash})"
                    )

            expected_prev = row_hash

        return (len(errors) == 0, errors, len(rows))
