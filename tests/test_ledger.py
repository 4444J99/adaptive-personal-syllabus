"""Tests for ledger append and verification."""

from __future__ import annotations

from pathlib import Path

from adaptive_personal_syllabus.ledger import Ledger
from adaptive_personal_syllabus.storage import Storage


def test_ledger_verify_success(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "ok.db")
    ledger = Ledger(storage)

    ledger.append("event.a", {"x": 1})
    ledger.append("event.b", {"y": 2})

    ok, errors, count = ledger.verify_chain()
    assert ok is True
    assert errors == []
    assert count == 2


def test_ledger_verify_detects_tamper(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "tamper.db")
    ledger = Ledger(storage)

    ledger.append("event.a", {"x": 1})
    ledger.append("event.b", {"y": 2})

    with storage.connection() as conn:
        conn.execute("UPDATE ledger_events SET payload_json = ? WHERE id = 1", ('{"x":999}',))

    ok, errors, count = ledger.verify_chain()
    assert ok is False
    assert count == 2
    assert any("event_hash mismatch" in err for err in errors)


def test_ledger_verify_malformed_first_row(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "malformed_first.db")
    ledger = Ledger(storage)

    ledger.append("event.a", {"x": 1})
    ledger.append("event.b", {"y": 2})

    with storage.connection() as conn:
        conn.execute("UPDATE ledger_events SET payload_json = ? WHERE id = 1", ("{broken-json",))

    ok, errors, count = ledger.verify_chain()
    assert ok is False
    assert count == 2
    assert any("event 1: malformed payload JSON" in err for err in errors)


def test_ledger_verify_malformed_middle_row(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "malformed_middle.db")
    ledger = Ledger(storage)

    ledger.append("event.a", {"x": 1})
    ledger.append("event.b", {"y": 2})
    ledger.append("event.c", {"z": 3})

    with storage.connection() as conn:
        conn.execute("UPDATE ledger_events SET payload_json = ? WHERE id = 2", ("{broken-json",))

    ok, errors, count = ledger.verify_chain()
    assert ok is False
    assert count == 3
    assert len(errors) == 1
    assert "event 2: malformed payload JSON" in errors[0]


def test_ledger_verify_malformed_last_row(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "malformed_last.db")
    ledger = Ledger(storage)

    ledger.append("event.a", {"x": 1})
    ledger.append("event.b", {"y": 2})

    with storage.connection() as conn:
        conn.execute("UPDATE ledger_events SET payload_json = ? WHERE id = 2", ("",))

    ok, errors, count = ledger.verify_chain()
    assert ok is False
    assert count == 2
    assert len(errors) == 1
    assert "event 2: malformed payload JSON" in errors[0]


def test_ledger_verify_multiple_errors(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "multiple_errors.db")
    ledger = Ledger(storage)

    ledger.append("event.a", {"x": 1})
    ledger.append("event.b", {"y": 2})
    ledger.append("event.c", {"z": 3})

    with storage.connection() as conn:
        conn.execute("UPDATE ledger_events SET payload_json = ? WHERE id = 1", ("{broken-json",))
        conn.execute("UPDATE ledger_events SET payload_json = ? WHERE id = 3", ('{"z": 999}',))

    ok, errors, count = ledger.verify_chain()
    assert ok is False
    assert count == 3
    assert len(errors) == 2
    assert any("event 1: malformed payload JSON" in err for err in errors)
    assert any("event 3: event_hash mismatch" in err for err in errors)


def test_ledger_verify_later_linkage_tampering(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "linkage_tamper.db")
    ledger = Ledger(storage)

    ledger.append("event.a", {"x": 1})
    ledger.append("event.b", {"y": 2})
    ledger.append("event.c", {"z": 3})

    with storage.connection() as conn:
        conn.execute("UPDATE ledger_events SET payload_json = ? WHERE id = 1", ("{broken-json",))
        conn.execute("UPDATE ledger_events SET prev_hash = ? WHERE id = 3", ("bad_prev_hash",))

    ok, errors, count = ledger.verify_chain()
    assert ok is False
    assert count == 3
    assert any("event 1: malformed payload JSON" in err for err in errors)
    assert any("event 3: prev_hash mismatch" in err for err in errors)


def test_ledger_verify_db_unchanged(tmp_path: Path) -> None:
    db_path = tmp_path / "unchanged.db"
    storage = Storage(db_path)
    ledger = Ledger(storage)

    ledger.append("event.a", {"x": 1})
    ledger.append("event.b", {"y": 2})

    with storage.connection() as conn:
        conn.execute("UPDATE ledger_events SET payload_json = ? WHERE id = 1", ("{broken-json",))

    db_bytes_before = db_path.read_bytes()
    with storage.connection() as conn:
        rows_before = conn.execute("SELECT * FROM ledger_events ORDER BY id ASC").fetchall()
        rows_before_dicts = [dict(r) for r in rows_before]

    ok, _errors, count = ledger.verify_chain()
    assert ok is False
    assert count == 2

    db_bytes_after = db_path.read_bytes()
    with storage.connection() as conn:
        rows_after = conn.execute("SELECT * FROM ledger_events ORDER BY id ASC").fetchall()
        rows_after_dicts = [dict(r) for r in rows_after]

    assert db_bytes_before == db_bytes_after
    assert rows_before_dicts == rows_after_dicts
