"""SQLite storage layer for corpus, planning, hooks, and ledger data."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_DATA_DIR = Path.home() / ".adaptive-syllabus"
DEFAULT_DB_PATH = DEFAULT_DATA_DIR / "adaptive_syllabus.db"
DEFAULT_PROFILE_PATH = DEFAULT_DATA_DIR / "profile.json"


def utcnow_iso() -> str:
    """UTC timestamp in ISO-8601 format."""
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


class Storage:
    """Small SQLite wrapper with methods used by CLI and services."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path or DEFAULT_DB_PATH).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize_schema()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return {str(row["name"]) for row in rows}

    @staticmethod
    def _cursor_lastrowid(cursor: sqlite3.Cursor) -> int:
        if cursor.lastrowid is None:
            raise RuntimeError("SQLite did not return lastrowid for insert operation")
        return int(cursor.lastrowid)

    def _backfill_snapshot_bindings(self, conn: sqlite3.Connection) -> None:
        unbound_docs = int(
            conn.execute("SELECT COUNT(*) FROM documents WHERE snapshot_id IS NULL").fetchone()[0]
        )
        unbound_plans = int(
            conn.execute("SELECT COUNT(*) FROM plans WHERE snapshot_id IS NULL").fetchone()[0]
        )
        if unbound_docs == 0 and unbound_plans == 0:
            return

        latest_snapshot = conn.execute(
            "SELECT id FROM snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if latest_snapshot:
            snapshot_id = int(latest_snapshot["id"])
        else:
            doc_count = int(conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
            unique_payload_count = int(
                conn.execute("SELECT COUNT(DISTINCT sha256) FROM documents").fetchone()[0]
            )
            cur = conn.execute(
                """
                INSERT INTO snapshots(snapshot_name, root_path, doc_count, unique_payload_count, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("legacy-migration", "unknown", doc_count, unique_payload_count, utcnow_iso()),
            )
            snapshot_id = self._cursor_lastrowid(cur)

        if unbound_docs:
            conn.execute(
                "UPDATE documents SET snapshot_id = ? WHERE snapshot_id IS NULL",
                (snapshot_id,),
            )
        if unbound_plans:
            conn.execute(
                "UPDATE plans SET snapshot_id = ? WHERE snapshot_id IS NULL",
                (snapshot_id,),
            )

    def _run_migrations(self, conn: sqlite3.Connection) -> None:
        document_columns = self._table_columns(conn, "documents")
        if "snapshot_id" not in document_columns:
            conn.execute("ALTER TABLE documents ADD COLUMN snapshot_id INTEGER")

        plan_columns = self._table_columns(conn, "plans")
        if "snapshot_id" not in plan_columns:
            conn.execute("ALTER TABLE plans ADD COLUMN snapshot_id INTEGER")

        # Remove old global uniqueness and replace with snapshot-scoped uniqueness.
        conn.execute("DROP INDEX IF EXISTS idx_documents_canonical_path")
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_snapshot_canonical_path
            ON documents(snapshot_id, canonical_path)
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_documents_snapshot_id ON documents(snapshot_id)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_plans_snapshot_id ON plans(snapshot_id)")

        conn.execute("""CREATE TABLE IF NOT EXISTS plan_payloads (
            plan_id INTEGER PRIMARY KEY REFERENCES plans(id),
            fingerprint_version INTEGER NOT NULL,
            fingerprint_sha256 TEXT NOT NULL,
            payload_json TEXT NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS source_judgments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL REFERENCES documents(id),
            payload_json TEXT NOT NULL)""")
        self._backfill_snapshot_bindings(conn)

    def initialize_schema(self) -> None:
        """Create database schema if it does not exist."""
        with self.connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_name TEXT NOT NULL,
                    root_path TEXT NOT NULL,
                    doc_count INTEGER NOT NULL,
                    unique_payload_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_snapshots_name
                    ON snapshots(snapshot_name);

                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_id INTEGER NOT NULL,
                    canonical_path TEXT NOT NULL,
                    rel_path TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    bytes INTEGER NOT NULL,
                    lines INTEGER NOT NULL,
                    mime TEXT NOT NULL,
                    family TEXT NOT NULL,
                    ingested_at TEXT NOT NULL,
                    FOREIGN KEY(snapshot_id) REFERENCES snapshots(id) ON DELETE CASCADE
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_snapshot_canonical_path
                    ON documents(snapshot_id, canonical_path);
                CREATE INDEX IF NOT EXISTS idx_documents_sha256
                    ON documents(sha256);
                CREATE INDEX IF NOT EXISTS idx_documents_snapshot_id
                    ON documents(snapshot_id);

                CREATE TABLE IF NOT EXISTS document_aliases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id INTEGER NOT NULL,
                    alias_path TEXT NOT NULL,
                    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_document_aliases_document_id
                    ON document_aliases(document_id);

                CREATE TABLE IF NOT EXISTS document_chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id INTEGER NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    heading_path TEXT NOT NULL,
                    text TEXT NOT NULL,
                    token_estimate INTEGER NOT NULL,
                    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_document_chunks_document_id
                    ON document_chunks(document_id);

                CREATE TABLE IF NOT EXISTS profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    level TEXT NOT NULL,
                    goals_json TEXT NOT NULL,
                    context_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS plans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile_id INTEGER NOT NULL,
                    snapshot_id INTEGER,
                    title TEXT NOT NULL,
                    total_hours REAL NOT NULL,
                    module_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(profile_id) REFERENCES profiles(id) ON DELETE CASCADE,
                    FOREIGN KEY(snapshot_id) REFERENCES snapshots(id) ON DELETE SET NULL
                );
                CREATE INDEX IF NOT EXISTS idx_plans_snapshot_id
                    ON plans(snapshot_id);

                CREATE TABLE IF NOT EXISTS plan_modules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    plan_id INTEGER NOT NULL,
                    seq INTEGER NOT NULL,
                    module_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    organ TEXT NOT NULL,
                    difficulty TEXT NOT NULL,
                    readings_json TEXT NOT NULL,
                    questions_json TEXT NOT NULL,
                    estimated_hours REAL NOT NULL,
                    FOREIGN KEY(plan_id) REFERENCES plans(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_plan_modules_plan_id
                    ON plan_modules(plan_id);

                CREATE TABLE IF NOT EXISTS hook_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    plan_id INTEGER,
                    hook_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    output_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(plan_id) REFERENCES plans(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS ledger_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prev_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_ledger_events_id
                    ON ledger_events(id);
                """
            )
            self._run_migrations(conn)

    def insert_snapshot(
        self,
        snapshot_name: str,
        root_path: str,
        doc_count: int,
        unique_payload_count: int,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> int:
        created_at = utcnow_iso()
        if conn is None:
            with self.connection() as db_conn:
                return self.insert_snapshot(
                    snapshot_name=snapshot_name,
                    root_path=root_path,
                    doc_count=doc_count,
                    unique_payload_count=unique_payload_count,
                    conn=db_conn,
                )
        cur = conn.execute(
            """
            INSERT INTO snapshots(snapshot_name, root_path, doc_count, unique_payload_count, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (snapshot_name, root_path, doc_count, unique_payload_count, created_at),
        )
        return self._cursor_lastrowid(cur)

    def resolve_snapshot(
        self,
        *,
        snapshot_id: int | None = None,
        snapshot_name: str | None = "latest",
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        if conn is None:
            with self.connection() as db_conn:
                return self.resolve_snapshot(
                    snapshot_id=snapshot_id,
                    snapshot_name=snapshot_name,
                    conn=db_conn,
                )

        row: sqlite3.Row | None
        if snapshot_id is not None:
            row = conn.execute("SELECT * FROM snapshots WHERE id = ?", (snapshot_id,)).fetchone()
        elif snapshot_name and snapshot_name != "latest":
            row = conn.execute(
                """
                SELECT * FROM snapshots
                WHERE snapshot_name = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (snapshot_name,),
            ).fetchone()
        else:
            row = conn.execute("SELECT * FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    def get_snapshot(
        self,
        snapshot_id: int,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        return self.resolve_snapshot(snapshot_id=snapshot_id, conn=conn)

    def latest_snapshot(self) -> dict[str, Any] | None:
        return self.resolve_snapshot(snapshot_name="latest")

    def insert_document(
        self,
        snapshot_id: int,
        canonical_path: str,
        rel_path: str,
        sha256: str,
        size_bytes: int,
        lines: int,
        mime: str,
        family: str,
        ingested_at: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> int:
        if conn is None:
            with self.connection() as db_conn:
                return self.insert_document(
                    snapshot_id=snapshot_id,
                    canonical_path=canonical_path,
                    rel_path=rel_path,
                    sha256=sha256,
                    size_bytes=size_bytes,
                    lines=lines,
                    mime=mime,
                    family=family,
                    ingested_at=ingested_at,
                    conn=db_conn,
                )
        cur = conn.execute(
            """
            INSERT INTO documents(
                snapshot_id, canonical_path, rel_path, sha256, bytes, lines, mime, family, ingested_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                canonical_path,
                rel_path,
                sha256,
                size_bytes,
                lines,
                mime,
                family,
                ingested_at,
            ),
        )
        return self._cursor_lastrowid(cur)

    def insert_aliases(
        self,
        document_id: int,
        alias_paths: Sequence[str],
        *,
        conn: sqlite3.Connection | None = None,
    ) -> int:
        if not alias_paths:
            return 0
        if conn is None:
            with self.connection() as db_conn:
                return self.insert_aliases(document_id, alias_paths, conn=db_conn)
        conn.executemany(
            "INSERT INTO document_aliases(document_id, alias_path) VALUES (?, ?)",
            [(document_id, alias_path) for alias_path in alias_paths],
        )
        return len(alias_paths)

    def insert_alias(
        self,
        document_id: int,
        alias_path: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        self.insert_aliases(document_id=document_id, alias_paths=[alias_path], conn=conn)

    def insert_chunks(
        self,
        document_id: int,
        chunks: Sequence[tuple[int, str, str, int]],
        *,
        conn: sqlite3.Connection | None = None,
    ) -> int:
        if not chunks:
            return 0
        if conn is None:
            with self.connection() as db_conn:
                return self.insert_chunks(document_id=document_id, chunks=chunks, conn=db_conn)
        conn.executemany(
            """
            INSERT INTO document_chunks(document_id, chunk_index, heading_path, text, token_estimate)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (document_id, chunk_index, heading_path, text, token_estimate)
                for chunk_index, heading_path, text, token_estimate in chunks
            ],
        )
        return len(chunks)

    def insert_chunk(
        self,
        document_id: int,
        chunk_index: int,
        heading_path: str,
        text: str,
        token_estimate: int,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        self.insert_chunks(
            document_id=document_id,
            chunks=[(chunk_index, heading_path, text, token_estimate)],
            conn=conn,
        )

    def corpus_stats(
        self,
        *,
        snapshot_id: int | None = None,
        snapshot_name: str | None = "latest",
    ) -> dict[str, Any]:
        """Stable JSON schema for corpus statistics."""
        with self.connection() as conn:
            selected = self.resolve_snapshot(
                snapshot_id=snapshot_id,
                snapshot_name=snapshot_name,
                conn=conn,
            )
            latest = self.resolve_snapshot(snapshot_name="latest", conn=conn)

            if selected is None:
                doc_count = 0
                alias_count = 0
                chunk_count = 0
                total_bytes = 0
                by_family_rows: list[sqlite3.Row] = []
            else:
                selected_id = int(selected["id"])
                doc_count = int(
                    conn.execute(
                        "SELECT COUNT(*) FROM documents WHERE snapshot_id = ?",
                        (selected_id,),
                    ).fetchone()[0]
                )
                alias_count = int(
                    conn.execute(
                        """
                        SELECT COUNT(*)
                        FROM document_aliases a
                        JOIN documents d ON d.id = a.document_id
                        WHERE d.snapshot_id = ?
                        """,
                        (selected_id,),
                    ).fetchone()[0]
                )
                chunk_count = int(
                    conn.execute(
                        """
                        SELECT COUNT(*)
                        FROM document_chunks c
                        JOIN documents d ON d.id = c.document_id
                        WHERE d.snapshot_id = ?
                        """,
                        (selected_id,),
                    ).fetchone()[0]
                )
                total_bytes = int(
                    conn.execute(
                        "SELECT COALESCE(SUM(bytes), 0) FROM documents WHERE snapshot_id = ?",
                        (selected_id,),
                    ).fetchone()[0]
                )
                by_family_rows = conn.execute(
                    """
                    SELECT family, COUNT(*) AS n
                    FROM documents
                    WHERE snapshot_id = ?
                    GROUP BY family
                    ORDER BY family
                    """,
                    (selected_id,),
                ).fetchall()

            ledger_events = int(conn.execute("SELECT COUNT(*) FROM ledger_events").fetchone()[0])

        family_breakdown = {str(row["family"]): int(row["n"]) for row in by_family_rows}
        return {
            "schema_version": "1.0",
            "snapshot_selector": {"snapshot_id": snapshot_id, "snapshot_name": snapshot_name},
            "snapshot": selected,
            "latest_snapshot": latest,
            "document_count": doc_count,
            "alias_count": alias_count,
            "chunk_count": chunk_count,
            "total_bytes": total_bytes,
            "family_breakdown": family_breakdown,
            "ledger_event_count": ledger_events,
        }

    def list_documents(
        self,
        *,
        snapshot_id: int,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT id, snapshot_id, canonical_path, rel_path, family, sha256
            FROM documents
            WHERE snapshot_id = ?
            ORDER BY canonical_path
        """
        params: tuple[Any, ...] = (snapshot_id,)
        if limit is not None:
            query += " LIMIT ?"
            params = (snapshot_id, limit)
        with self.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def list_snapshot_sha256(self, snapshot_id: int) -> list[str]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT sha256
                FROM documents
                WHERE snapshot_id = ?
                ORDER BY sha256
                """,
                (snapshot_id,),
            ).fetchall()
        return [str(row["sha256"]) for row in rows]

    def list_document_chunks(self, *, snapshot_id: int) -> list[dict[str, Any]]:
        """Return inspectable text chunks for bounded local source selection."""
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT d.snapshot_id, d.id AS document_id, d.canonical_path, d.rel_path, d.sha256,
                       c.chunk_index, c.heading_path, c.text
                FROM document_chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE d.snapshot_id = ?
                ORDER BY d.canonical_path, c.chunk_index
                """,
                (snapshot_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def insert_profile(
        self,
        name: str,
        level: str,
        goals: list[str],
        context: dict[str, Any],
    ) -> int:
        created_at = utcnow_iso()
        with self.connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO profiles(name, level, goals_json, context_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (name, level, json.dumps(goals), json.dumps(context), created_at),
            )
            return self._cursor_lastrowid(cur)

    def insert_plan(
        self,
        profile_id: int,
        title: str,
        total_hours: float,
        module_count: int,
        snapshot_id: int | None,
    ) -> int:
        created_at = utcnow_iso()
        with self.connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO plans(profile_id, snapshot_id, title, total_hours, module_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (profile_id, snapshot_id, title, total_hours, module_count, created_at),
            )
            return self._cursor_lastrowid(cur)

    def insert_plan_module(
        self,
        plan_id: int,
        seq: int,
        module_id: str,
        title: str,
        organ: str,
        difficulty: str,
        readings: list[str],
        questions: list[str],
        estimated_hours: float,
    ) -> int:
        with self.connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO plan_modules(
                    plan_id, seq, module_id, title, organ, difficulty, readings_json, questions_json,
                    estimated_hours
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan_id,
                    seq,
                    module_id,
                    title,
                    organ,
                    difficulty,
                    json.dumps(readings),
                    json.dumps(questions),
                    estimated_hours,
                ),
            )
            return self._cursor_lastrowid(cur)

    def insert_hook_run(
        self,
        plan_id: int | None,
        hook_name: str,
        status: str,
        output: dict[str, Any],
    ) -> int:
        created_at = utcnow_iso()
        with self.connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO hook_runs(plan_id, hook_name, status, output_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (plan_id, hook_name, status, json.dumps(output), created_at),
            )
            return self._cursor_lastrowid(cur)

    def last_ledger_hash(self, *, conn: sqlite3.Connection | None = None) -> str:
        if conn is None:
            with self.connection() as db_conn:
                return self.last_ledger_hash(conn=db_conn)
        row = conn.execute(
            "SELECT event_hash FROM ledger_events ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return str(row["event_hash"]) if row else ""

    def append_ledger_event(
        self,
        prev_hash: str,
        event_hash: str,
        event_type: str,
        payload: dict[str, Any],
        created_at: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> int:
        if conn is None:
            with self.connection() as db_conn:
                return self.append_ledger_event(
                    prev_hash=prev_hash,
                    event_hash=event_hash,
                    event_type=event_type,
                    payload=payload,
                    created_at=created_at,
                    conn=db_conn,
                )
        cur = conn.execute(
            """
            INSERT INTO ledger_events(prev_hash, event_hash, event_type, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (prev_hash, event_hash, event_type, json.dumps(payload, sort_keys=True), created_at),
        )
        return self._cursor_lastrowid(cur)

    def iter_ledger_events(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM ledger_events ORDER BY id ASC").fetchall()
        return [dict(r) for r in rows]

    def insert_complete_plan(self, plan: dict[str, Any]) -> int:
        """Atomically persist both compatible projections and the exact versioned payload."""
        json.dumps(plan, allow_nan=False)
        with self.connection() as conn:
            profile = plan["profile"]
            cur = conn.execute(
                "INSERT INTO profiles(name,level,goals_json,context_json,created_at) VALUES(?,?,?,?,?)",
                (
                    profile["name"],
                    profile["level"],
                    json.dumps(profile["goals"]),
                    json.dumps(profile["context"]),
                    utcnow_iso(),
                ),
            )
            profile_id = self._cursor_lastrowid(cur)
            cur = conn.execute(
                "INSERT INTO plans(profile_id,snapshot_id,title,total_hours,module_count,created_at) VALUES(?,?,?,?,?,?)",
                (
                    profile_id,
                    plan["snapshot"]["id"],
                    plan["title"],
                    plan["totals"]["total_hours"],
                    plan["totals"]["module_count"],
                    utcnow_iso(),
                ),
            )
            plan_id = self._cursor_lastrowid(cur)
            for m in plan["modules"]:
                conn.execute(
                    "INSERT INTO plan_modules(plan_id,seq,module_id,title,organ,difficulty,readings_json,questions_json,estimated_hours) VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        plan_id,
                        m["seq"],
                        m["module_id"],
                        m["title"],
                        m["organ"],
                        m["difficulty"],
                        json.dumps(m["readings"]),
                        json.dumps(m["questions"]),
                        m["estimated_hours"],
                    ),
                )
            payload = dict(plan, db_plan_id=plan_id)
            conn.execute(
                "INSERT INTO plan_payloads VALUES(?,?,?,?)",
                (
                    plan_id,
                    plan["determinism_inputs"]["fingerprint_schema_version"],
                    plan["fingerprint_sha256"],
                    json.dumps(payload, allow_nan=False),
                ),
            )
        return plan_id

    def get_plan(self, plan_id: int) -> dict[str, Any] | None:
        """Retrieve by database key; never silently reconstruct a historical fingerprint."""
        with self.connection() as conn:
            payload = conn.execute(
                "SELECT payload_json FROM plan_payloads WHERE plan_id=?", (plan_id,)
            ).fetchone()
            if payload:
                return json.loads(payload[0])
            row = conn.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()
            if row is None:
                return None
            profile = dict(
                conn.execute("SELECT * FROM profiles WHERE id=?", (row["profile_id"],)).fetchone()
            )
            modules = []
            for m in conn.execute(
                "SELECT * FROM plan_modules WHERE plan_id=? ORDER BY seq", (plan_id,)
            ):
                item = dict(m)
                item["readings"] = json.loads(item.pop("readings_json"))
                item["questions"] = json.loads(item.pop("questions_json"))
                modules.append(item)
            profile["goals"] = json.loads(profile.pop("goals_json"))
            profile["context"] = json.loads(profile.pop("context_json"))
            return {
                "schema_version": "legacy_projection",
                "db_plan_id": plan_id,
                "plan_id": None,
                "fingerprint_sha256": None,
                "historical_integrity": "original_payload_and_fingerprint_not_stored",
                "title": row["title"],
                "profile": profile,
                "modules": modules,
                "totals": {"module_count": row["module_count"], "total_hours": row["total_hours"]},
            }

    def get_passage(self, document_id: int, chunk_index: int) -> dict[str, Any] | None:
        """Read snapshot text even when the original external file is no longer available."""
        with self.connection() as conn:
            row = conn.execute(
                """SELECT d.snapshot_id,d.id AS document_id,d.sha256,d.rel_path,
                c.chunk_index,c.heading_path,c.text FROM document_chunks c
                JOIN documents d ON d.id=c.document_id WHERE d.id=? AND c.chunk_index=?""",
                (document_id, chunk_index),
            ).fetchone()
            if row is None:
                return None
            result = dict(row)
            result["aliases"] = [
                r[0]
                for r in conn.execute(
                    "SELECT alias_path FROM document_aliases WHERE document_id=? ORDER BY alias_path",
                    (document_id,),
                )
            ]
            result["document_completeness"] = "not_established"
            return result

    def record_source_judgment(self, record: dict[str, Any]) -> int:
        """Append an attributed judgment after verifying its exact snapshot passage."""
        from .support import validate_judgment

        validate_judgment(self, record)
        with self.connection() as conn:
            cur = conn.execute(
                "INSERT INTO source_judgments(document_id,payload_json) VALUES(?,?)",
                (record["document_id"], json.dumps(record, allow_nan=False)),
            )
            return self._cursor_lastrowid(cur)

    def list_source_judgments(
        self, document_id: int | None = None, *, snapshot_id: int | None = None
    ) -> list[dict[str, Any]]:
        """Read document or snapshot judgments, preserving cross-source contradictions."""
        if (document_id is None) == (snapshot_id is None):
            raise ValueError("Select exactly one document_id or snapshot_id")
        selector = document_id if document_id is not None else snapshot_id
        if type(selector) is not int or selector <= 0:
            raise ValueError("Source judgment selector must be a positive integer")
        column = "j.document_id" if document_id is not None else "d.snapshot_id"
        with self.connection() as conn:
            return [
                json.loads(r[0])
                for r in conn.execute(
                    "SELECT j.payload_json FROM source_judgments j "
                    "JOIN documents d ON d.id=j.document_id "
                    f"WHERE {column}=? ORDER BY j.id",
                    (selector,),
                )
            ]
