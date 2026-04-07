import json
import logging
import sqlite3
import threading
from dataclasses import asdict

from rathausrot.models import CouncilItem, Session

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = "processed_items.db"


class DatabaseManager:
    """Centralized database connection manager with pooling."""

    _pools: dict = {}
    _lock = threading.Lock()

    @classmethod
    def get_connection(cls, db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
        if db_path not in cls._pools:
            with cls._lock:
                if db_path not in cls._pools:
                    conn = sqlite3.connect(db_path, check_same_thread=False)
                    conn.execute("PRAGMA journal_mode=WAL")
                    conn.execute("PRAGMA synchronous=NORMAL")
                    conn.execute("PRAGMA cache_size=-64000")
                    cls._pools[db_path] = conn
        return cls._pools[db_path]

    @classmethod
    def close_all(cls) -> None:
        with cls._lock:
            for conn in cls._pools.values():
                conn.close()
            cls._pools.clear()


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
                "error_msg TEXT DEFAULT '')"
            )
            conn.commit()

    def record_run(self, item_count: int, success: bool, error_msg: str = "") -> None:
        with DatabaseManager.get_connection(self.db_path) as conn:
            conn.execute(
                "INSERT INTO run_history (item_count, success, error_msg) VALUES (?, ?, ?)",
                (item_count, 1 if success else 0, error_msg),
            )
            conn.commit()

    def get_recent(self, limit: int = 10) -> list[dict]:
        with DatabaseManager.get_connection(self.db_path) as conn:
            rows = conn.execute(
                "SELECT ran_at, item_count, success, error_msg FROM run_history "
                "ORDER BY ran_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "ran_at": row[0],
                "item_count": row[1],
                "success": bool(row[2]),
                "error_msg": row[3],
            }
            for row in rows
        ]


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
                "INSERT OR REPLACE INTO retry_queue (item_id, item_json, attempts) "
                "VALUES (?, ?, ?)",
                (item.id, json.dumps(asdict(item)), new_attempts),
            )
            conn.commit()

    def get_pending(self, max_attempts: int = 3) -> list:
        with DatabaseManager.get_connection(self.db_path) as conn:
            rows = conn.execute(
                "SELECT item_json FROM retry_queue WHERE attempts < ? ORDER BY added_at",
                (max_attempts,),
            ).fetchall()
        items = []
        for row in rows:
            data = json.loads(row[0])
            items.append(CouncilItem(**data))
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
                "(item_id, title, url, date, item_type, source_system, body_text) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    item.id,
                    item.title,
                    item.url,
                    item.date,
                    item.item_type,
                    item.source_system,
                    item.body_text,
                ),
            )
            conn.commit()

    def get_all_as_items(self, limit: int = 500) -> list[CouncilItem]:
        """Return all stored items as CouncilItem objects (no pdf_texts/pdf_urls)."""
        with DatabaseManager.get_connection(self.db_path) as conn:
            rows = conn.execute(
                "SELECT item_id, title, url, date, item_type, source_system, body_text "
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
        pattern = f"%{query}%"
        with DatabaseManager.get_connection(self.db_path) as conn:
            rows = conn.execute(
                "SELECT item_id, title, url, date, source_system, stored_at "
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
