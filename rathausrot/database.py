import contextlib
import json
import logging
import sqlite3
import threading
from dataclasses import asdict

from rathausrot.models import CouncilItem, Session

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = "processed_items.db"


class DatabaseManager:
    """Centralized database connection manager.

    Each (thread, db_path) pair gets one shared connection stored in a
    process-wide registry. ``close_all`` shuts down every connection the
    process owns, regardless of which thread opened it, so that daemon
    threads (listener, healthcheck, manual-scrape) do not leak SQLite handles
    on shutdown.
    """

    _local = threading.local()
    _all_connections: list[sqlite3.Connection] = []
    _registry_lock = threading.Lock()

    @classmethod
    def get_connection(cls, db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
        if not hasattr(cls._local, "connections"):
            cls._local.connections = {}
        if db_path not in cls._local.connections:
            conn = sqlite3.connect(db_path)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=-64000")
            cls._local.connections[db_path] = conn
            with cls._registry_lock:
                cls._all_connections.append(conn)
        return cls._local.connections[db_path]

    @classmethod
    def close_all(cls) -> None:
        """Schließt alle bekannten Connections prozessweit."""
        with cls._registry_lock:
            conns = cls._all_connections
            cls._all_connections = []
        for conn in conns:
            with contextlib.suppress(Exception):
                conn.close()
        # Drop thread-local references so a recycled thread can't
        # resurrect a closed handle after close_all.
        if hasattr(cls._local, "connections"):
            cls._local.connections.clear()


class DuplicateTracker:
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with DatabaseManager.get_connection(self.db_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS processed_items "
                "(item_id TEXT PRIMARY KEY, processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
            )
            conn.commit()

    def is_new(self, item_id: str) -> bool:
        with DatabaseManager.get_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT 1 FROM processed_items WHERE item_id = ?", (item_id,)
            ).fetchone()
        return row is None

    def mark_processed(self, item_id: str) -> None:
        with DatabaseManager.get_connection(self.db_path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO processed_items (item_id) VALUES (?)", (item_id,)
            )
            conn.commit()

    def check_and_mark_batch(self, item_ids: list[str]) -> list[str]:
        """Check multiple items at once and mark them as processed. Returns only new item IDs."""
        if not item_ids:
            return []
        with DatabaseManager.get_connection(self.db_path) as conn:
            placeholders = ",".join("?" * len(item_ids))
            rows = conn.execute(
                f"SELECT item_id FROM processed_items WHERE item_id IN ({placeholders})",
                item_ids,
            ).fetchall()
            known_ids = {row[0] for row in rows}
            new_ids = [item_id for item_id in item_ids if item_id not in known_ids]
            if new_ids:
                conn.executemany(
                    "INSERT OR IGNORE INTO processed_items (item_id) VALUES (?)",
                    [(item_id,) for item_id in new_ids],
                )
                conn.commit()
        return new_ids


class RunHistoryTracker:
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with DatabaseManager.get_connection(self.db_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS run_history "
                "(id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "ran_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
                "item_count INTEGER DEFAULT 0, "
                "success INTEGER DEFAULT 1, "
                "error_msg TEXT DEFAULT '', "
                "tokens_used INTEGER DEFAULT 0)"
            )
            # Migration: add tokens_used to databases created before this column existed
            existing_cols = {
                row[1] for row in conn.execute("PRAGMA table_info(run_history)")
            }
            if "tokens_used" not in existing_cols:
                conn.execute(
                    "ALTER TABLE run_history ADD COLUMN tokens_used INTEGER DEFAULT 0"
                )
            conn.commit()

    def record_run(
        self,
        item_count: int,
        success: bool,
        error_msg: str = "",
        tokens: int = 0,
    ) -> None:
        with DatabaseManager.get_connection(self.db_path) as conn:
            conn.execute(
                "INSERT INTO run_history (item_count, success, error_msg, tokens_used) "
                "VALUES (?, ?, ?, ?)",
                (item_count, 1 if success else 0, error_msg, int(tokens)),
            )
            conn.commit()

    def get_recent(self, limit: int = 10) -> list[dict]:
        with DatabaseManager.get_connection(self.db_path) as conn:
            rows = conn.execute(
                "SELECT ran_at, item_count, success, error_msg, tokens_used "
                "FROM run_history ORDER BY ran_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "ran_at": row[0],
                "item_count": row[1],
                "success": bool(row[2]),
                "error_msg": row[3],
                "tokens_used": row[4],
            }
            for row in rows
        ]

    def get_token_stats(self, days: int = 30) -> dict:
        """Aggregate token usage and item counts over the last `days` days."""
        with DatabaseManager.get_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(tokens_used), 0), COALESCE(SUM(item_count), 0), "
                "COUNT(*) FROM run_history "
                "WHERE ran_at >= datetime('now', ?) AND success = 1",
                (f"-{int(days)} days",),
            ).fetchone()
        return {
            "tokens": row[0],
            "items": row[1],
            "runs": row[2],
            "days": days,
        }

    def get_consecutive_failures(self) -> int:
        """Return how many of the most recent runs failed in an unbroken streak."""
        with DatabaseManager.get_connection(self.db_path) as conn:
            rows = conn.execute(
                "SELECT success FROM run_history ORDER BY id DESC"
            ).fetchall()
        count = 0
        for (success,) in rows:
            if success:
                break
            count += 1
        return count


class RetryQueue:
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with DatabaseManager.get_connection(self.db_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS retry_queue "
                "(item_id TEXT PRIMARY KEY, item_json TEXT, "
                "added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
                "attempts INTEGER DEFAULT 0)"
            )
            conn.commit()

    def add(self, item: CouncilItem, max_attempts: int = 3) -> None:
        with DatabaseManager.get_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT attempts FROM retry_queue WHERE item_id = ?", (item.id,)
            ).fetchone()
            current_attempts = row[0] if row else 0
            new_attempts = current_attempts + 1
            if new_attempts > max_attempts:
                logger.warning(
                    "RetryQueue: Item %s hat maximale Versuche (%d) erreicht, wird verworfen",
                    item.id,
                    max_attempts,
                )
                return
            conn.execute(
                "INSERT INTO retry_queue (item_id, item_json, attempts) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(item_id) DO UPDATE SET "
                "attempts = excluded.attempts, "
                "item_json = excluded.item_json",
                (item.id, json.dumps(asdict(item)), new_attempts),
            )
            conn.commit()

    def get_pending(self, max_attempts: int = 3) -> list[CouncilItem]:
        with DatabaseManager.get_connection(self.db_path) as conn:
            rows = conn.execute(
                "SELECT item_id, item_json FROM retry_queue WHERE attempts < ? ORDER BY added_at",
                (max_attempts,),
            ).fetchall()
        items: list[CouncilItem] = []
        for item_id, item_json in rows:
            try:
                data = json.loads(item_json)
                items.append(CouncilItem(**data))
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                logger.error("Corrupt retry queue entry %s, removing: %s", item_id, exc)
                with contextlib.suppress(Exception):
                    self.remove(item_id)
        return items

    def remove(self, item_id: str) -> None:
        with DatabaseManager.get_connection(self.db_path) as conn:
            conn.execute("DELETE FROM retry_queue WHERE item_id = ?", (item_id,))
            conn.commit()


class CouncilItemStore:
    """Persistent archive of scraped CouncilItems for full-text search."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with DatabaseManager.get_connection(self.db_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS council_items "
                "(item_id TEXT PRIMARY KEY, title TEXT, url TEXT, "
                "date TEXT, item_type TEXT, source_system TEXT, "
                "body_text TEXT, "
                "stored_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
            )
            # Schema migration: add city_name/committee columns to existing DBs
            # that were created before multi-city support was added.
            existing_cols = {
                row[1] for row in conn.execute("PRAGMA table_info(council_items)")
            }
            if "city_name" not in existing_cols:
                conn.execute(
                    "ALTER TABLE council_items ADD COLUMN city_name TEXT DEFAULT ''"
                )
            if "committee" not in existing_cols:
                conn.execute(
                    "ALTER TABLE council_items ADD COLUMN committee TEXT DEFAULT ''"
                )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS known_sessions "
                "(id TEXT PRIMARY KEY, title TEXT, date TEXT, url TEXT, "
                "announced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_council_items_title "
                "ON council_items (title)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_council_items_stored_at "
                "ON council_items (stored_at DESC)"
            )
            conn.commit()

    def store(self, item: CouncilItem) -> None:
        with DatabaseManager.get_connection(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO council_items "
                "(item_id, title, url, date, item_type, source_system, body_text, "
                "city_name, committee) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    item.id,
                    item.title,
                    item.url,
                    item.date,
                    item.item_type,
                    item.source_system,
                    item.body_text,
                    item.city_name,
                    item.committee,
                ),
            )
            conn.commit()

    def get_all_as_items(self, limit: int = 500) -> list[CouncilItem]:
        """Return all stored items as CouncilItem objects (no pdf_texts/pdf_urls)."""
        with DatabaseManager.get_connection(self.db_path) as conn:
            rows = conn.execute(
                "SELECT item_id, title, url, date, item_type, source_system, "
                "body_text, city_name, committee "
                "FROM council_items ORDER BY stored_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            CouncilItem(
                id=r[0],
                title=r[1],
                url=r[2],
                date=r[3],
                item_type=r[4],
                source_system=r[5],
                body_text=r[6],
                city_name=r[7],
                committee=r[8],
            )
            for r in rows
        ]

    _SQLITE_BATCH_SIZE = 500

    def get_new_sessions(self, sessions: list[Session]) -> list[Session]:
        """Return sessions not yet in known_sessions."""
        if not sessions:
            return []
        session_ids = [s.id for s in sessions]
        known_ids: set = set()
        with DatabaseManager.get_connection(self.db_path) as conn:
            for i in range(0, len(session_ids), self._SQLITE_BATCH_SIZE):
                batch = session_ids[i : i + self._SQLITE_BATCH_SIZE]
                placeholders = ",".join("?" * len(batch))
                rows = conn.execute(
                    f"SELECT id FROM known_sessions WHERE id IN ({placeholders})",
                    batch,
                ).fetchall()
                known_ids.update(row[0] for row in rows)
        return [s for s in sessions if s.id not in known_ids]

    def mark_session_announced(self, session: Session) -> None:
        with DatabaseManager.get_connection(self.db_path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO known_sessions (id, title, date, url) VALUES (?, ?, ?, ?)",
                (session.id, session.title, session.date, session.url),
            )
            conn.commit()

    def search(self, query: str, limit: int = 10) -> list[dict]:
        escaped = query.replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        with DatabaseManager.get_connection(self.db_path) as conn:
            rows = conn.execute(
                "SELECT item_id, title, url, date, source_system, stored_at, "
                "city_name, committee "
                "FROM council_items "
                "WHERE title LIKE ? OR body_text LIKE ? "
                "ORDER BY stored_at DESC LIMIT ?",
                (pattern, pattern, limit),
            ).fetchall()
        return [
            {
                "id": r[0],
                "title": r[1],
                "url": r[2],
                "date": r[3],
                "source_system": r[4],
                "stored_at": r[5],
                "city_name": r[6],
                "committee": r[7],
            }
            for r in rows
        ]


class LLMCache:
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with DatabaseManager.get_connection(self.db_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS llm_cache "
                "(item_id TEXT PRIMARY KEY, result_json TEXT, "
                "cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
            )
            conn.commit()

    def get(self, item_id: str) -> dict | None:
        with DatabaseManager.get_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT result_json FROM llm_cache WHERE item_id = ?", (item_id,)
            ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def put(self, item_id: str, result) -> None:
        with DatabaseManager.get_connection(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO llm_cache (item_id, result_json) VALUES (?, ?)",
                (item_id, json.dumps(asdict(result))),
            )
            conn.commit()


# Tables eligible for time-based retention cleanup: (table, timestamp_column)
_RETENTION_TABLES = (
    ("llm_cache", "cached_at"),
    ("council_items", "stored_at"),
    ("run_history", "ran_at"),
    ("processed_items", "processed_at"),
)


def cleanup_old_entries(
    days: int = 180, vacuum: bool = False, db_path: str = DEFAULT_DB_PATH
) -> dict[str, int]:
    """Delete rows older than `days` from retention-managed tables.

    Returns a mapping of table name to the number of deleted rows. A
    non-positive `days` value disables cleanup and returns an empty dict.
    Missing tables are skipped gracefully. When `vacuum` is True the database
    file is compacted afterwards (slower, reclaims disk space).
    """
    if days <= 0:
        return {}
    cutoff = f"-{int(days)} days"
    conn = DatabaseManager.get_connection(db_path)
    deleted: dict[str, int] = {}
    for table, column in _RETENTION_TABLES:
        try:
            cursor = conn.execute(
                f"DELETE FROM {table} WHERE {column} < datetime('now', ?)",  # noqa: S608 – table/column are fixed literals
                (cutoff,),
            )
            deleted[table] = cursor.rowcount
        except sqlite3.OperationalError:
            # Table does not exist yet – nothing to clean up.
            deleted[table] = 0
    conn.commit()
    if vacuum:
        conn.execute("VACUUM")
    total = sum(deleted.values())
    logger.info("DB cleanup removed %d rows older than %d days", total, days)
    return deleted
