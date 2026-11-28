"""Phone-terminal width: learner-facing text wraps, machine output does not.

ADR 010 — the loop stays CLI, and its learner-facing terminal text wraps
to the live terminal width so a 40-column phone SSH session reads without
horizontal scrolling. The width comes from the terminal itself
(``os.get_terminal_size`` on stdout), never from the environment: the
repo's public-surface contract (ADR 005, #42) forbids ``os.environ`` /
``getenv`` in src modules. JSON formats stay unwrapped (machine output)
and artifact file bytes stay unchanged (authorization-bound, ADR 009).

The CLI-level tests run the installed ``syllabus`` entry point under a
real pty with a set window size — the same mechanism a phone SSH session
uses — rather than monkeypatching the environment.
"""

from __future__ import annotations

import fcntl
import json
import os
import pty
import struct
import subprocess
import sys
import termios
from pathlib import Path

import pytest
from click.testing import CliRunner

from adaptive_personal_syllabus.core import (
    _render_plan_markdown,
    _terminal_width,
    _wrap_terminal_lines,
    cli,
)
from adaptive_personal_syllabus.corpus import CorpusIngestor
from adaptive_personal_syllabus.ledger import Ledger
from adaptive_personal_syllabus.planner import Planner
from adaptive_personal_syllabus.storage import Storage
from tests.test_planner import _profile, _seed_dir

PHONE_WIDTH = 40


@pytest.fixture
def phone_plan(tmp_path: Path) -> tuple[int, str]:
    """A synthetic plan for a phone-only, audio-medium learner; returns (plan_id, db_path)."""
    storage = Storage(tmp_path / "db.sqlite")
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "a.md").write_text("# Foundations\nFoundations need evidence.\n")
    CorpusIngestor(storage, Ledger(storage)).ingest(root, "synthetic")
    planner = Planner(storage, Ledger(storage), _seed_dir(tmp_path))
    profile_path = _profile(
        tmp_path,
        access_conditions={"phone_only": True},
        medium="audio",
        learning_purpose="evaluate",
        output_policy={"selected_wings": ["academic"]},
    )
    plan = planner.generate(profile_path)
    return plan["db_plan_id"], str(storage.db_path)


def _syllabus_bin() -> str:
    """The installed ``syllabus`` entry point next to this test's Python."""
    return str(Path(sys.executable).with_name("syllabus"))


def _run_on_pty(argv: list[str], cols: int, timeout: int = 30) -> tuple[int, str]:
    """Run argv with stdout on a pty of the given width; return (exit code, output)."""
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, cols, 0, 0))
    proc = subprocess.Popen(
        argv, stdout=slave, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
        text=True, close_fds=True,
    )
    os.close(slave)
    chunks: list[str] = []
    try:
        while True:
            try:
                data = os.read(master, 65536)
            except OSError:
                break
            if not data:
                break
            chunks.append(data.decode("utf-8", errors="replace"))
    finally:
        os.close(master)
    proc.wait(timeout=timeout)
    return proc.returncode, "".join(chunks)


def _assert_wrapped(output: str, width: int) -> None:
    """Every line fits the width, except lines that cannot wrap without splitting.

    A line is exempt only when it is a single whitespace-free token (a
    fingerprint) or a ``**...**`` metadata line carrying one — wrapping
    either would split the token it names.
    """
    for line in output.splitlines():
        assert (
            len(line) <= width or len(line.split()) <= 1 or line.startswith("**")
        ), f"line exceeds {width} cols: {line!r}"


def test_plan_encounter_text_wraps_on_phone_pty(phone_plan) -> None:
    plan_id, db_path = phone_plan
    code, out = _run_on_pty(
        [_syllabus_bin(), "plan", "encounter", str(plan_id), "--db-path", db_path],
        PHONE_WIDTH,
    )
    assert code == 0, out
    _assert_wrapped(out, PHONE_WIDTH)
    assert "Phone route" in out
    # Same words, only re-wrapped: compare against a wide-terminal run.
    _, wide = _run_on_pty(
        [_syllabus_bin(), "plan", "encounter", str(plan_id), "--db-path", db_path],
        200,
    )
    assert out.split() == wide.split()


def test_plan_show_text_and_md_wrap_on_phone_pty(phone_plan) -> None:
    plan_id, db_path = phone_plan
    plan = Storage(Path(db_path)).get_plan(plan_id)
    assert plan is not None
    for fmt in ("text", "md"):
        code, out = _run_on_pty(
            [_syllabus_bin(), "plan", "show", str(plan_id), "--format", fmt,
             "--db-path", db_path],
            PHONE_WIDTH,
        )
        assert code == 0, out
        _assert_wrapped(out, PHONE_WIDTH)
        # The plan fingerprint stays whole: never split across lines.
        assert plan["plan_id"] in out
    _, md = _run_on_pty(
        [_syllabus_bin(), "plan", "show", str(plan_id), "--format", "md",
         "--db-path", db_path],
        PHONE_WIDTH,
    )
    assert "## 1." in md
    assert "\n- " in md
    assert "**Plan ID:**" in md


def test_plan_generate_text_wraps_on_phone_pty(tmp_path) -> None:
    storage = Storage(tmp_path / "db.sqlite")
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "a.md").write_text("# Foundations\nFoundations need evidence.\n")
    CorpusIngestor(storage, Ledger(storage)).ingest(root, "synthetic")
    code, out = _run_on_pty(
        [
            _syllabus_bin(), "plan", "generate", "--format", "text",
            "--profile", str(_profile(tmp_path)),
            "--seed-dir", str(_seed_dir(tmp_path)),
            "--db-path", str(storage.db_path),
        ],
        PHONE_WIDTH,
    )
    assert code == 0, out
    _assert_wrapped(out, PHONE_WIDTH)


def test_json_formats_stay_unwrapped_on_phone_pty(phone_plan) -> None:
    plan_id, db_path = phone_plan
    for args in (
        ["plan", "show", str(plan_id), "--format", "json"],
        ["plan", "encounter", str(plan_id), "--format", "json"],
    ):
        code, out = _run_on_pty(
            [_syllabus_bin(), *args, "--db-path", db_path], PHONE_WIDTH
        )
        assert code == 0, out
        assert json.loads(out)["db_plan_id"] == plan_id


def test_terminal_width_uses_the_tty(tmp_path) -> None:
    # No tty in this test process: no width is known, so no wrap.
    assert _terminal_width() is None
    # A 5-column terminal floors at the 20-column minimum.
    code, out = _run_on_pty(
        [sys.executable, "-c",
         "from adaptive_personal_syllabus.core import _terminal_width; print(_terminal_width())"],
        5,
    )
    assert code == 0, out
    assert out.strip() == "20"
    # A 40-column terminal reports 40.
    code, out = _run_on_pty(
        [sys.executable, "-c",
         "from adaptive_personal_syllabus.core import _terminal_width; print(_terminal_width())"],
        40,
    )
    assert code == 0, out
    assert out.strip() == "40"


def test_piped_output_stays_unwrapped(phone_plan) -> None:
    """The historical bytes are pinned: without a terminal, nothing wraps."""
    plan_id, db_path = phone_plan
    runner = CliRunner()
    result = runner.invoke(
        cli, ["plan", "show", str(plan_id), "--format", "md", "--db-path", db_path]
    )
    assert result.exit_code == 0, result.output
    plan = Storage(Path(db_path)).get_plan(plan_id)
    assert plan is not None
    assert result.output.rstrip("\n") == _render_plan_markdown(plan)


def test_wrap_keeps_list_items_valid() -> None:
    lines = _wrap_terminal_lines(
        ["- Choose one claim about Foundations and seek a counterexample."],
        width=40,
    )
    assert lines[0].startswith("- Choose")
    assert len(lines) > 1
    assert all(line.startswith("  ") for line in lines[1:])
    assert all(len(line) <= 40 for line in lines)
