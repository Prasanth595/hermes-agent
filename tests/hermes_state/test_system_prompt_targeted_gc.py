"""Per-turn prompt and tools-pin writes do not scan the whole ``system_prompts`` table.

A prompt rebuild, a tools-pin update or a session creation can only orphan the hash it replaced
or the one it inserted. Checking just those keeps the write-lock hold time of a routine turn
independent of how many prompts the store holds; deletes and prunes keep the full sweep.
"""

import json

import pytest

from hermes_state import SessionDB


@pytest.fixture()
def db(tmp_path):
    session_db = SessionDB(db_path=tmp_path / "state.db")
    yield session_db
    session_db.close()


def _prompts(db):
    with db._read_ctx() as conn:
        return {row[0] for row in conn.execute("SELECT prompt FROM system_prompts")}


def _add_sessions_with_distinct_prompts(db, start, count):
    def seed(conn):
        for i in range(start, start + count):
            conn.execute("INSERT INTO system_prompts (hash, prompt) VALUES (?, ?)", (f"h{i}", f"prompt {i}"))
            conn.execute("INSERT INTO sessions (id, source, started_at, system_prompt_hash) "
                         "VALUES (?, 'cli', 0, ?)", (f"bulk{i}", f"h{i}"))
    db._execute_write(seed)


def _vm_steps(db, write):
    """SQLite VM instructions (in units of 100) the writer connection runs for *write*."""
    steps = [0]

    def count():
        steps[0] += 1
        return 0
    db._execute_write(lambda conn: conn.set_progress_handler(count, 100))
    try:
        write()
    finally:
        db._execute_write(lambda conn: conn.set_progress_handler(None, 100))
    return steps[0]


_WRITES = {
    "system_prompt": lambda db, i: db.update_system_prompt("s1", f"rebuilt {i}"),
    "tool_names": lambda db, i: db.update_session_tool_names("s1", {"version": str(i), "tools": []}),
    "create_session": lambda db, i: db.create_session(f"new{i}", "cli", system_prompt=f"fresh {i}"),
}


@pytest.mark.parametrize("name", list(_WRITES))
def test_per_turn_write_cost_does_not_grow_with_the_prompt_table(db, name):
    write = _WRITES[name]
    db.create_session("s1", "cli", system_prompt="original")
    _add_sessions_with_distinct_prompts(db, 0, 10)
    write(db, 0)  # warm up statement caches
    small = _vm_steps(db, lambda: write(db, 1))
    _add_sessions_with_distinct_prompts(db, 10, 2000)
    large = _vm_steps(db, lambda: write(db, 2))
    # A full sweep visits every prompt row: ~60x more work on main at 2,010 rows than at 10.
    assert large <= 2 * small + 5, (small, large)


def test_worker_prompt_and_tools_pin_write_cost_does_not_grow(worker):
    db, store = worker

    def write(i):
        store.update_system_prompt("owned", f"rebuilt {i}")
        store.update_session_tool_names("owned", {"version": str(i), "tools": []})
    write(0)
    small = _vm_steps(db, lambda: write(1))
    _add_sessions_with_distinct_prompts(db, 0, 2000)
    large = _vm_steps(db, lambda: write(2))
    assert large <= 2 * small + 5, (small, large)


def test_released_hash_is_kept_while_a_prompt_or_tools_pin_still_references_it(db):
    pin = ["terminal", "read_file"]
    shared = json.dumps(pin)  # identical bytes share one content-addressed row
    db.create_session("s1", "cli", system_prompt=shared)
    db.create_session("s2", "cli", system_prompt=shared)
    db.create_session("s3", "cli")
    db.update_session_tool_names("s3", pin)

    db.update_system_prompt("s1", "rebuilt")
    assert shared in _prompts(db)  # still s2's prompt
    db.update_system_prompt("s2", "rebuilt")
    assert shared in _prompts(db)  # still s3's tools pin
    db.update_session_tool_names("s3", None)
    assert _prompts(db) == {"rebuilt"}


def test_discarded_session_releases_its_prompt_and_tools_pin(db):
    pin = {"version": "1", "tools": []}
    db.create_session("kept", "cli", system_prompt="kept prompt")
    db.update_session_tool_names("kept", pin)
    db.create_session("seed", "cli", system_prompt="seed prompt")
    db.update_session_tool_names("seed", pin)

    assert db.discard_unadmitted_session("seed") is True

    assert _prompts(db) == {"kept prompt", json.dumps(pin)}
