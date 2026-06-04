import contextlib
import os
import sqlite3
import tempfile

import pytest

from rathausrot.database import (
    DatabaseManager,
    RunHistoryTracker,
    LLMCache,
    CouncilItemStore,
    cleanup_old_entries,
)
from rathausrot.llm_client import LLMResult
from rathausrot.models import CouncilItem


@pytest.fixture
def db_path():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    try:
        yield path
    finally:
        DatabaseManager.close_all()
        for suffix in ("", "-wal", "-shm"):
            with contextlib.suppress(OSError):
                os.unlink(path + suffix)


# ------------------------------------------------------------------ #
# Token tracking
# ------------------------------------------------------------------ #


def test_record_run_stores_tokens(db_path):
    tracker = RunHistoryTracker(db_path)
    tracker.record_run(3, True, tokens=1500)
    recent = tracker.get_recent(1)
    assert recent[0]["tokens_used"] == 1500


def test_get_token_stats_sums_successful_runs(db_path):
    tracker = RunHistoryTracker(db_path)
    tracker.record_run(2, True, tokens=1000)
    tracker.record_run(3, True, tokens=2000)
    tracker.record_run(0, False, "err", tokens=999)  # failures ignored
    stats = tracker.get_token_stats(30)
    assert stats["tokens"] == 3000
    assert stats["items"] == 5
    assert stats["runs"] == 2
    assert stats["days"] == 30


def test_tokens_used_migration_on_old_schema(db_path):
    # Simulate a pre-existing DB without the tokens_used column.
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE run_history "
        "(id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "ran_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
        "item_count INTEGER DEFAULT 0, success INTEGER DEFAULT 1, "
        "error_msg TEXT DEFAULT '')"
    )
    conn.commit()
    conn.close()

    tracker = RunHistoryTracker(db_path)  # _init_db must add the column
    tracker.record_run(1, True, tokens=42)
    assert tracker.get_token_stats(30)["tokens"] == 42


# ------------------------------------------------------------------ #
# Consecutive failures
# ------------------------------------------------------------------ #


def test_consecutive_failures_counts_streak(db_path):
    tracker = RunHistoryTracker(db_path)
    tracker.record_run(1, True)
    tracker.record_run(0, False, "a")
    tracker.record_run(0, False, "b")
    assert tracker.get_consecutive_failures() == 2


def test_consecutive_failures_reset_by_success(db_path):
    tracker = RunHistoryTracker(db_path)
    tracker.record_run(0, False, "a")
    tracker.record_run(1, True)
    assert tracker.get_consecutive_failures() == 0


def test_consecutive_failures_empty(db_path):
    tracker = RunHistoryTracker(db_path)
    assert tracker.get_consecutive_failures() == 0


# ------------------------------------------------------------------ #
# Retention cleanup
# ------------------------------------------------------------------ #


def test_cleanup_removes_old_rows(db_path):
    tracker = RunHistoryTracker(db_path)
    cache = LLMCache(db_path)
    store = CouncilItemStore(db_path)

    # Fresh rows
    tracker.record_run(1, True, tokens=10)
    cache.put("fresh", LLMResult(summary="x"))
    store.store(
        CouncilItem(
            id="fresh",
            title="Fresh",
            url="http://e/1",
            item_type="item",
            date="",
            body_text="",
        )
    )

    # Inject an old row directly with a backdated timestamp
    conn = DatabaseManager.get_connection(db_path)
    conn.execute(
        "INSERT INTO llm_cache (item_id, result_json, cached_at) "
        "VALUES ('old', '{}', datetime('now', '-400 days'))"
    )
    conn.execute(
        "INSERT INTO council_items (item_id, title, url, stored_at) "
        "VALUES ('old', 'Old', 'http://e/0', datetime('now', '-400 days'))"
    )
    conn.commit()

    deleted = cleanup_old_entries(days=180, db_path=db_path)
    assert deleted["llm_cache"] == 1
    assert deleted["council_items"] == 1

    assert cache.get("old") is None
    assert cache.get("fresh") is not None


def test_cleanup_disabled_returns_empty(db_path):
    RunHistoryTracker(db_path)
    assert cleanup_old_entries(days=0, db_path=db_path) == {}


def test_cleanup_missing_tables_is_graceful(db_path):
    # No tables created at all – cleanup must not raise.
    DatabaseManager.get_connection(db_path)
    deleted = cleanup_old_entries(days=30, db_path=db_path)
    assert all(count == 0 for count in deleted.values())
