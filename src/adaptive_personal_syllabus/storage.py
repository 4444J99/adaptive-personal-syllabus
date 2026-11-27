"""SQLite storage layer for corpus, planning, hooks, and ledger data."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_DATA_DIR = Path.home() / ".adaptive-syllabus"
DEFAULT_DB_PATH = DEFAULT_DATA_DIR / "adaptive_syllabus.db"
DEFAULT_PROFILE_PATH = DEFAULT_DATA_DIR / "profile.json"

# Live-source refresh (#54, MTR-018): default per-source freshness bound.
# A source whose last good retrieval is older than its bound reads `stale`.
DEFAULT_MAX_AGE_HOURS = 168  # 7 days

# Outcomes `corpus refresh` records, one per source per run (plan step 4).
REFRESH_OUTCOMES = (
    "ok",
    "unchanged",
    "changed",
    "timeout",
    "rate_limited",
    "revoked",
    "deleted",
    "error",
)
# Outcomes that carry readable bytes (a content version, not a marker).
REFRESH_CONTENT_OUTCOMES = ("ok", "unchanged", "changed")
# Outcomes whose latest observation means "last good version still usable,
# but marked failed" (plan step 6).
REFRESH_FAILED_OUTCOMES = ("timeout", "rate_limited", "error")


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
        # Ledger checkpoint (#52, MTR-022): one row, the latest committed
        # chain head. Earlier checkpoints are superseded — the ledger
        # itself is the history — so the table keeps a single row (id 1).
        conn.execute("""CREATE TABLE IF NOT EXISTS ledger_checkpoints (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            event_count INTEGER NOT NULL,
            head_hash TEXT NOT NULL,
            created_at TEXT NOT NULL)""")

        # Live-source refresh (#54, MTR-018). `source_records` is the stable
        # identity of a source across snapshots (one row per root + rel path);
        # `source_versions` is the append-only observation history for that
        # source — one row per content version plus one marker row per
        # failure / deletion / revocation observation (sha256 NULL there:
        # the bytes were not read, or the file was gone). `refresh_runs`
        # records one row per `corpus refresh` invocation with its outcome
        # counts. A refresh never rewrites snapshots or document rows.
        conn.execute("""CREATE TABLE IF NOT EXISTS source_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            root_path TEXT NOT NULL,
            rel_path TEXT NOT NULL,
            max_age_hours INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(root_path, rel_path))""")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_source_records_root ON source_records(root_path)"
        )
        conn.execute("""CREATE TABLE IF NOT EXISTS source_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER NOT NULL REFERENCES source_records(id) ON DELETE CASCADE,
            sha256 TEXT,
            source_version TEXT NOT NULL,
            retrieved_at TEXT NOT NULL,
            outcome TEXT NOT NULL,
            detail_json TEXT NOT NULL,
            snapshot_id INTEGER REFERENCES snapshots(id) ON DELETE SET NULL)""")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_source_versions_source_id "
            "ON source_versions(source_id)"
        )
        conn.execute("""CREATE TABLE IF NOT EXISTS refresh_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            root_path TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            outcome_counts_json TEXT NOT NULL)""")

        # Source admission (#48, MTR-017). One row per decision; the latest
        # row for a (root_path, rel_path, sha256) source wins. Admission
        # binds to exact bytes, so a sha drift leaves the source
        # unadmitted until re-admitted. Admit rows carry the mandatory
        # fields; revoke rows carry revoked_by / revocation_reason and
        # NULL admit fields. No row means `unadmitted`.
        conn.execute("""CREATE TABLE IF NOT EXISTS source_admissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            root_path TEXT NOT NULL,
            rel_path TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            document_id INTEGER NOT NULL,
            decision TEXT NOT NULL,
            owner TEXT,
            license TEXT,
            access TEXT,
            provenance TEXT,
            admitted_by TEXT,
            admission_basis TEXT,
            reviewer TEXT,
            reviewed_at TEXT,
            admitted_at TEXT,
            revoked_by TEXT,
            revocation_reason TEXT,
            revoked_at TEXT)""")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_source_admissions_source "
            "ON source_admissions(root_path, rel_path, sha256)"
        )

        # Content kind (#48 step 3): passage (decoded text exists) /
        # metadata_only (binary intake, no extraction) / extraction_failed.
        # Backfill by family: only binary intake is metadata-only at
        # ingest time (text files decode or fail the ingest outright).
        document_columns = self._table_columns(conn, "documents")
        if "content_kind" not in document_columns:
            conn.execute("ALTER TABLE documents ADD COLUMN content_kind TEXT")
            conn.execute(
                "UPDATE documents SET content_kind = "
                "CASE WHEN family = 'binary' THEN 'metadata_only' ELSE 'passage' END"
            )
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
                    content_kind TEXT NOT NULL DEFAULT 'passage',
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
        content_kind: str = "passage",
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
                    content_kind=content_kind,
                    conn=db_conn,
                )
        cur = conn.execute(
            """
            INSERT INTO documents(
                snapshot_id, canonical_path, rel_path, sha256, bytes, lines, mime, family,
                content_kind, ingested_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                content_kind,
                ingested_at,
            ),
        )
        return self._cursor_lastrowid(cur)

    def get_document(
        self,
        document_id: int,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        """One document row with its snapshot's root path (source identity)."""
        if conn is None:
            with self.connection() as db_conn:
                return self.get_document(document_id, conn=db_conn)
        row = conn.execute(
            """
            SELECT d.*, s.root_path AS root_path
            FROM documents d
            JOIN snapshots s ON s.id = d.snapshot_id
            WHERE d.id = ?
            """,
            (document_id,),
        ).fetchone()
        return dict(row) if row else None

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
            # Live-source refresh (#54): per-source freshness for the selected
            # snapshot's documents. Imported here so storage stays importable
            # without the freshness module (it only type-checks Storage).
            source_freshness = None
            if selected is not None:
                from .freshness import summarize_snapshot_freshness

                source_freshness = summarize_snapshot_freshness(
                    self, snapshot_id=selected_id, conn=conn
                )
                # Source admission (#48 step 7): a `private`-access
                # decision redacts the source's path from every output
                # surface, including this freshness block.
                admission_map = self.admission_map_for_snapshot(
                    selected_id, conn=conn
                )
                for item in source_freshness["sources"]:
                    access = admission_map.get(int(item["document_id"]), {}).get("access")
                    if access == "private":
                        item["rel_path"] = "[redacted: private]"

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
            "source_freshness": source_freshness,
        }

    def list_documents(
        self,
        *,
        snapshot_id: int,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT id, snapshot_id, canonical_path, rel_path, family, sha256, content_kind
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
                       d.content_kind, c.chunk_index, c.heading_path, c.text
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

    def ledger_event_count(self, *, conn: sqlite3.Connection | None = None) -> int:
        if conn is None:
            with self.connection() as db_conn:
                return self.ledger_event_count(conn=db_conn)
        row = conn.execute("SELECT COUNT(*) FROM ledger_events").fetchone()
        return int(row[0])

    def record_ledger_checkpoint(
        self,
        event_count: int,
        head_hash: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        """Replace the latest checkpoint with the given chain head.

        Callers pass the connection their ledger append already uses, so
        the checkpoint commits or rolls back with that append.
        """
        if conn is None:
            with self.connection() as db_conn:
                return self.record_ledger_checkpoint(event_count, head_hash, conn=db_conn)
        conn.execute("DELETE FROM ledger_checkpoints")
        conn.execute(
            """
            INSERT INTO ledger_checkpoints(id, event_count, head_hash, created_at)
            VALUES (1, ?, ?, ?)
            """,
            (event_count, head_hash, utcnow_iso()),
        )

    def latest_ledger_checkpoint(
        self, *, conn: sqlite3.Connection | None = None
    ) -> dict[str, Any] | None:
        if conn is None:
            with self.connection() as db_conn:
                return self.latest_ledger_checkpoint(conn=db_conn)
        row = conn.execute(
            "SELECT event_count, head_hash, created_at FROM ledger_checkpoints WHERE id = 1"
        ).fetchone()
        return dict(row) if row else None

    def plans_missing_ledger_events(self) -> list[int]:
        """Plan rows with no matching plan.generate ledger event.

        A plan row and its plan.generate event are written in one
        transaction (#52); a row without its event means the write
        sequence did not complete. Snapshots have no equivalent check:
        corpus ingest legitimately creates snapshots with no docs.audit
        event, so only plans are cross-checked here.
        """
        with self.connection() as conn:
            plan_ids = [
                int(row[0]) for row in conn.execute("SELECT id FROM plans").fetchall()
            ]
            event_plan_ids: set[int] = set()
            for row in conn.execute(
                "SELECT payload_json FROM ledger_events WHERE event_type = 'plan.generate'"
            ).fetchall():
                try:
                    payload = json.loads(str(row[0]))
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
                if isinstance(payload, dict) and isinstance(
                    payload.get("db_plan_id"), int
                ):
                    event_plan_ids.add(int(payload["db_plan_id"]))
        return [plan_id for plan_id in plan_ids if plan_id not in event_plan_ids]

    def iter_ledger_events(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM ledger_events ORDER BY id ASC").fetchall()
        return [dict(r) for r in rows]

    def insert_complete_plan(
        self, plan: dict[str, Any], *, conn: sqlite3.Connection | None = None
    ) -> int:
        """Atomically persist both compatible projections and the exact versioned payload."""
        json.dumps(plan, allow_nan=False)
        cm = nullcontext(conn) if conn is not None else self.connection()
        with cm as db_conn:
            conn = db_conn
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
        """Read snapshot text even when the original external file is no longer available.

        `document_completeness` is computed from the stored state (#48
        step 3): a chunk-bearing passage document is `complete`; the
        hard-coded `not_established` is gone. A document with no chunk
        at this index returns None — the caller reports a `metadata_only`
        document by kind instead of erroring on a missing passage.
        """
        with self.connection() as conn:
            row = conn.execute(
                """SELECT d.snapshot_id,d.id AS document_id,d.sha256,d.rel_path,
                d.content_kind,
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
            result["document_completeness"] = "complete"
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

    # -- Judgment invalidation (#50, MTR-020) -------------------------------

    def _supersede_judgment_row(
        self,
        conn: sqlite3.Connection,
        judgment_id: int,
        *,
        snapshot_id: int,
        reason: str,
    ) -> bool:
        """Mark one stored judgment superseded in place; history is kept.

        Why in place: the row keeps every original field and gains
        ``status: superseded`` plus the superseding snapshot and reason,
        so the superseded judgment stays readable as history and never
        reads as live support. Returns False when already superseded.
        """
        row = conn.execute(
            "SELECT payload_json FROM source_judgments WHERE id=?", (judgment_id,)
        ).fetchone()
        if row is None:
            return False
        payload = json.loads(row[0])
        if payload.get("status") == "superseded":
            return False
        payload["status"] = "superseded"
        payload["superseded_by_snapshot_id"] = snapshot_id
        payload["superseded_at"] = utcnow_iso()
        payload["superseded_reason"] = reason
        conn.execute(
            "UPDATE source_judgments SET payload_json=? WHERE id=?",
            (json.dumps(payload, allow_nan=False), judgment_id),
        )
        return True

    def supersede_stale_judgments(
        self, snapshot_id: int, *, conn: sqlite3.Connection | None = None
    ) -> dict[str, Any]:
        """Supersede prior-snapshot judgments whose source text changed.

        Why at ingest: a new snapshot for a document whose chunk sha256
        changed means the old judgments speak about old bytes. Documents
        are per-snapshot rows, so the link is (snapshot root_path,
        rel_path): same source, new snapshot, different content. An
        unchanged re-ingest supersedes nothing — same bytes, same evidence.
        """
        if conn is None:
            with self.connection() as db_conn:
                return self.supersede_stale_judgments(snapshot_id, conn=db_conn)
        snapshot = conn.execute(
            "SELECT root_path FROM snapshots WHERE id=?", (snapshot_id,)
        ).fetchone()
        if snapshot is None:
            raise ValueError(f"Unknown snapshot {snapshot_id}")
        root_path = str(snapshot[0])
        new_docs = conn.execute(
            "SELECT id, rel_path, sha256 FROM documents WHERE snapshot_id=?",
            (snapshot_id,),
        ).fetchall()
        superseded: list[dict[str, Any]] = []
        for doc in new_docs:
            prior = conn.execute(
                "SELECT d.id FROM documents d JOIN snapshots s ON s.id=d.snapshot_id "
                "WHERE s.root_path=? AND d.rel_path=? AND d.snapshot_id < ? "
                "AND d.sha256 != ?",
                (root_path, str(doc["rel_path"]), snapshot_id, str(doc["sha256"])),
            ).fetchall()
            for (prior_id,) in prior:
                rows = conn.execute(
                    "SELECT id FROM source_judgments WHERE document_id=?",
                    (int(prior_id),),
                ).fetchall()
                for (judgment_id,) in rows:
                    if self._supersede_judgment_row(
                        conn, int(judgment_id), snapshot_id=snapshot_id,
                        reason="source_changed",
                    ):
                        superseded.append(
                            {
                                "judgment_id": int(judgment_id),
                                "document_id": int(prior_id),
                                "superseded_by_snapshot_id": snapshot_id,
                            }
                        )
        return {
            "snapshot_id": snapshot_id,
            "superseded": len(superseded),
            "judgments": superseded,
        }

    def revalidate_judgments(
        self, *, snapshot_id: int | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        """Re-check live judgments against a snapshot; supersede stale ones.

        Why a separate pass: judgments can go stale without a superseding
        ingest — recorded against an old snapshot after a newer one
        already exists, or recorded before invalidation shipped. The
        check is the same one ingest applies: the judgment's passage must
        still occur in the same document's chunk at the target snapshot.
        Defaults to the latest snapshot.
        """
        if conn is None:
            with self.connection() as db_conn:
                return self.revalidate_judgments(snapshot_id=snapshot_id, conn=db_conn)
        if snapshot_id is None:
            latest = conn.execute(
                "SELECT id FROM snapshots ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if latest is None:
                return {"snapshot_id": None, "checked": 0, "superseded": 0, "judgments": []}
            snapshot_id = int(latest[0])
        target_docs = {
            str(row["rel_path"]): int(row["id"])
            for row in conn.execute(
                "SELECT id, rel_path FROM documents WHERE snapshot_id=?",
                (snapshot_id,),
            ).fetchall()
        }
        rows = conn.execute(
            "SELECT id, document_id, payload_json FROM source_judgments ORDER BY id"
        ).fetchall()
        checked = 0
        superseded: list[dict[str, Any]] = []
        for judgment_id, document_id, payload_json in rows:
            payload = json.loads(payload_json)
            if payload.get("status") == "superseded":
                continue
            checked += 1
            doc = conn.execute(
                "SELECT rel_path FROM documents WHERE id=?", (int(document_id),)
            ).fetchone()
            reason: str | None = None
            if doc is None:
                reason = "source_absent"
            else:
                target_id = target_docs.get(str(doc[0]))
                if target_id is None:
                    reason = "source_absent"
                else:
                    passage = self.get_passage(
                        target_id, int(payload.get("chunk_index", 0))
                    )
                    if (
                        passage is None
                        or passage["sha256"] != payload.get("sha256")
                        or str(payload.get("passage", "")) not in str(passage["text"])
                    ):
                        reason = "source_changed"
            if reason is not None and self._supersede_judgment_row(
                conn, int(judgment_id), snapshot_id=snapshot_id, reason=reason
            ):
                superseded.append(
                    {
                        "judgment_id": int(judgment_id),
                        "document_id": int(document_id),
                        "reason": reason,
                        "superseded_by_snapshot_id": snapshot_id,
                    }
                )
        return {
            "snapshot_id": snapshot_id,
            "checked": checked,
            "superseded": len(superseded),
            "judgments": superseded,
        }

    # -- Live-source refresh (#54, MTR-018) ---------------------------------

    def find_source_record(
        self,
        root_path: str,
        rel_path: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        """The stable identity row for one source, or None (never refreshed)."""
        if conn is None:
            with self.connection() as db_conn:
                return self.find_source_record(root_path, rel_path, conn=db_conn)
        row = conn.execute(
            "SELECT * FROM source_records WHERE root_path = ? AND rel_path = ?",
            (root_path, rel_path),
        ).fetchone()
        return dict(row) if row else None

    def get_or_create_source_record(
        self,
        root_path: str,
        rel_path: str,
        max_age_hours: int = DEFAULT_MAX_AGE_HOURS,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        """Create the identity row on first sight; never reset an existing bound."""
        existing = self.find_source_record(root_path, rel_path, conn=conn)
        if existing is not None:
            return existing
        if conn is None:
            with self.connection() as db_conn:
                return self.get_or_create_source_record(
                    root_path, rel_path, max_age_hours, conn=db_conn
                )
        cur = conn.execute(
            """
            INSERT INTO source_records(root_path, rel_path, max_age_hours, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (root_path, rel_path, max_age_hours, utcnow_iso()),
        )
        record_id = self._cursor_lastrowid(cur)
        row = conn.execute(
            "SELECT * FROM source_records WHERE id = ?", (record_id,)
        ).fetchone()
        return dict(row)

    def set_source_max_age(
        self,
        source_id: int,
        max_age_hours: int,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        """Set one source's freshness bound (operator decision, per source)."""
        if max_age_hours <= 0:
            raise ValueError("max_age_hours must be positive")
        if conn is None:
            with self.connection() as db_conn:
                self.set_source_max_age(source_id, max_age_hours, conn=db_conn)
                return
        conn.execute(
            "UPDATE source_records SET max_age_hours = ? WHERE id = ?",
            (max_age_hours, source_id),
        )

    def insert_source_version(
        self,
        source_id: int,
        sha256: str | None,
        source_version: str,
        retrieved_at: str,
        outcome: str,
        detail: dict[str, Any],
        snapshot_id: int | None = None,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> int:
        """Append one refresh observation (content version or marker row)."""
        if outcome not in REFRESH_OUTCOMES:
            raise ValueError(f"Unknown refresh outcome: {outcome}")
        if conn is None:
            with self.connection() as db_conn:
                return self.insert_source_version(
                    source_id,
                    sha256,
                    source_version,
                    retrieved_at,
                    outcome,
                    detail,
                    snapshot_id,
                    conn=db_conn,
                )
        cur = conn.execute(
            """
            INSERT INTO source_versions(
                source_id, sha256, source_version, retrieved_at, outcome, detail_json,
                snapshot_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (source_id, sha256, source_version, retrieved_at, outcome,
             json.dumps(detail, sort_keys=True), snapshot_id),
        )
        return self._cursor_lastrowid(cur)

    def latest_source_version(
        self,
        source_id: int,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        """The newest observation for a source, content version or marker."""
        if conn is None:
            with self.connection() as db_conn:
                return self.latest_source_version(source_id, conn=db_conn)
        row = conn.execute(
            "SELECT * FROM source_versions WHERE source_id = ? ORDER BY id DESC LIMIT 1",
            (source_id,),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["detail"] = json.loads(str(row["detail_json"]))
        return result

    def latest_content_version(
        self,
        source_id: int,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        """The newest observation that carried readable bytes (the last good)."""
        if conn is None:
            with self.connection() as db_conn:
                return self.latest_content_version(source_id, conn=db_conn)
        placeholders = ",".join("?" for _ in REFRESH_CONTENT_OUTCOMES)
        row = conn.execute(
            f"SELECT * FROM source_versions WHERE source_id = ? "
            f"AND outcome IN ({placeholders}) ORDER BY id DESC LIMIT 1",
            (source_id, *REFRESH_CONTENT_OUTCOMES),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["detail"] = json.loads(str(row["detail_json"]))
        return result

    def touch_source_version(
        self,
        version_id: int,
        retrieved_at: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        """Advance a content version's confirmation time without a new row.

        Idempotent replay (#54 step 3): same bytes, no new version — but the
        re-read confirms the bytes now, so the recorded retrieval time moves
        and the source does not false-positive stale.
        """
        if conn is None:
            with self.connection() as db_conn:
                self.touch_source_version(version_id, retrieved_at, conn=db_conn)
                return
        conn.execute(
            "UPDATE source_versions SET retrieved_at = ? WHERE id = ?",
            (retrieved_at, version_id),
        )

    def list_source_records(
        self,
        root_path: str | None = None,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        """All source identity rows, optionally scoped to one ingest root."""
        if conn is None:
            with self.connection() as db_conn:
                return self.list_source_records(root_path, conn=db_conn)
        if root_path is None:
            rows = conn.execute("SELECT * FROM source_records ORDER BY root_path, rel_path")
        else:
            rows = conn.execute(
                "SELECT * FROM source_records WHERE root_path = ? ORDER BY rel_path",
                (root_path,),
            )
        return [dict(row) for row in rows.fetchall()]

    def list_snapshot_source_keys(
        self,
        snapshot_id: int,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        """One row per document in a snapshot, keyed to its source identity."""
        if conn is None:
            with self.connection() as db_conn:
                return self.list_snapshot_source_keys(snapshot_id, conn=db_conn)
        rows = conn.execute(
            """
            SELECT d.id AS document_id, s.root_path AS root_path,
                   d.rel_path AS rel_path, d.sha256 AS sha256
            FROM documents d
            JOIN snapshots s ON s.id = d.snapshot_id
            WHERE d.snapshot_id = ?
            ORDER BY d.rel_path
            """,
            (snapshot_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def insert_refresh_run(
        self,
        root_path: str,
        started_at: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> int:
        if conn is None:
            with self.connection() as db_conn:
                return self.insert_refresh_run(root_path, started_at, conn=db_conn)
        cur = conn.execute(
            """
            INSERT INTO refresh_runs(root_path, started_at, outcome_counts_json)
            VALUES (?, ?, ?)
            """,
            (root_path, started_at, json.dumps({})),
        )
        return self._cursor_lastrowid(cur)

    def finish_refresh_run(
        self,
        run_id: int,
        outcome_counts: dict[str, int],
        finished_at: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        if conn is None:
            with self.connection() as db_conn:
                self.finish_refresh_run(run_id, outcome_counts, finished_at, conn=db_conn)
                return
        conn.execute(
            """
            UPDATE refresh_runs
            SET finished_at = ?, outcome_counts_json = ?
            WHERE id = ?
            """,
            (finished_at, json.dumps(outcome_counts, sort_keys=True), run_id),
        )

    # -- Source admission (#48, MTR-017) ------------------------------------

    def record_source_admission(
        self,
        row: dict[str, Any],
        *,
        conn: sqlite3.Connection | None = None,
    ) -> int:
        """Append one admission decision row (admit or revoke)."""
        if conn is None:
            with self.connection() as db_conn:
                return self.record_source_admission(row, conn=db_conn)
        cur = conn.execute(
            """
            INSERT INTO source_admissions(
                root_path, rel_path, sha256, document_id, decision,
                owner, license, access, provenance, admitted_by,
                admission_basis, reviewer, reviewed_at, admitted_at,
                revoked_by, revocation_reason, revoked_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["root_path"],
                row["rel_path"],
                row["sha256"],
                row["document_id"],
                row["decision"],
                row.get("owner"),
                row.get("license"),
                row.get("access"),
                row.get("provenance"),
                row.get("admitted_by"),
                row.get("admission_basis"),
                row.get("reviewer"),
                row.get("reviewed_at"),
                row.get("admitted_at"),
                row.get("revoked_by"),
                row.get("revocation_reason"),
                row.get("revoked_at"),
            ),
        )
        return self._cursor_lastrowid(cur)

    def latest_source_admission(
        self,
        root_path: str,
        rel_path: str,
        sha256: str | None = None,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        """The latest decision for one source identity.

        With `sha256`, only a decision bound to those exact bytes counts.
        Without it, the latest decision for the source regardless of bytes
        (refresh uses this: a revoked source's bytes are never re-read).
        """
        if conn is None:
            with self.connection() as db_conn:
                return self.latest_source_admission(
                    root_path, rel_path, sha256, conn=db_conn
                )
        if sha256 is None:
            rows = conn.execute(
                """
                SELECT * FROM source_admissions
                WHERE root_path = ? AND rel_path = ?
                ORDER BY id DESC LIMIT 1
                """,
                (root_path, rel_path),
            ).fetchone()
        else:
            rows = conn.execute(
                """
                SELECT * FROM source_admissions
                WHERE root_path = ? AND rel_path = ? AND sha256 = ?
                ORDER BY id DESC LIMIT 1
                """,
                (root_path, rel_path, sha256),
            ).fetchone()
        return dict(rows) if rows is not None else None

    def admission_map_for_snapshot(
        self,
        snapshot_id: int,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[int, dict[str, Any]]:
        """One admission state per document in a snapshot.

        Status is `admitted` only when the latest decision bound to the
        document's exact bytes is `admitted`; otherwise the decision
        (`rejected` / `revoked`) or `unadmitted` when no row exists.
        """
        if conn is None:
            with self.connection() as db_conn:
                return self.admission_map_for_snapshot(snapshot_id, conn=db_conn)
        docs = conn.execute(
            """
            SELECT d.id AS document_id, s.root_path AS root_path,
                   d.rel_path AS rel_path, d.sha256 AS sha256
            FROM documents d
            JOIN snapshots s ON s.id = d.snapshot_id
            WHERE d.snapshot_id = ?
            """,
            (snapshot_id,),
        ).fetchall()
        result: dict[int, dict[str, Any]] = {}
        for doc in docs:
            row = self.latest_source_admission(
                str(doc["root_path"]),
                str(doc["rel_path"]),
                sha256=str(doc["sha256"]),
                conn=conn,
            )
            decision = str(row["decision"]) if row is not None else "unadmitted"
            result[int(doc["document_id"])] = {
                "status": decision,
                "decision": decision,
                "access": str(row["access"]) if row is not None and row.get("access") else None,
            }
        return result
