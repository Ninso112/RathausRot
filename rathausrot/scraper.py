import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass, field, asdict
from io import BytesIO
from pathlib import Path
from typing import Iterator, List, Optional
from urllib.robotparser import RobotFileParser
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from rathausrot.utils import RATSINFO_USER_AGENT, rate_limit_sleep, truncate_text

logger = logging.getLogger(__name__)

_ALLOWED_SCHEMES = {"http", "https"}


def _is_safe_url(url: str) -> bool:
    return urlparse(url).scheme in _ALLOWED_SCHEMES


@dataclass
class CouncilItem:
    id: str
    title: str
    url: str
    item_type: str
    date: str
    body_text: str
    pdf_texts: List[str] = field(default_factory=list)
    source_system: str = "unknown"


class DuplicateTracker:
    def __init__(self, db_path: str = "processed_items.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS processed_items "
                "(item_id TEXT PRIMARY KEY, processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
            )
            conn.commit()

    def is_new(self, item_id: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT 1 FROM processed_items WHERE item_id = ?", (item_id,)
            ).fetchone()
        return row is None

    def mark_processed(self, item_id: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO processed_items (item_id) VALUES (?)", (item_id,)
            )
            conn.commit()


class RunHistoryTracker:
    def __init__(self, db_path: str = "processed_items.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
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
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO run_history (item_count, success, error_msg) VALUES (?, ?, ?)",
                (item_count, 1 if success else 0, error_msg),
            )
            conn.commit()

    def get_recent(self, limit: int = 10) -> List[dict]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT ran_at, item_count, success, error_msg FROM run_history "
                "ORDER BY ran_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {"ran_at": row[0], "item_count": row[1], "success": bool(row[2]), "error_msg": row[3]}
            for row in rows
        ]


class RetryQueue:
    def __init__(self, db_path: str = "processed_items.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS retry_queue "
                "(item_id TEXT PRIMARY KEY, item_json TEXT, "
                "added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
                "attempts INTEGER DEFAULT 0)"
            )
            conn.commit()

    def add(self, item: "CouncilItem") -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO retry_queue (item_id, item_json, attempts) "
                "VALUES (?, ?, COALESCE((SELECT attempts FROM retry_queue WHERE item_id = ?), 0) + 1)",
                (item.id, json.dumps(asdict(item)), item.id),
            )
            conn.commit()

    def get_pending(self, max_attempts: int = 3) -> list:
        with sqlite3.connect(self.db_path) as conn:
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
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM retry_queue WHERE item_id = ?", (item_id,))
            conn.commit()


class LLMCache:
    def __init__(self, db_path: str = "processed_items.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS llm_cache "
                "(item_id TEXT PRIMARY KEY, result_json TEXT, "
                "cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
            )
            conn.commit()

    def get(self, item_id: str) -> Optional[dict]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT result_json FROM llm_cache WHERE item_id = ?", (item_id,)
            ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def put(self, item_id: str, result) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO llm_cache (item_id, result_json) VALUES (?, ?)",
                (item_id, json.dumps(asdict(result))),
            )
            conn.commit()


class RatsinfoScraper:
    def __init__(self, config: dict):
        self.config = config
        self.base_url = config.get("scraper", {}).get("ratsinfo_url", "")
        self.timeout = config.get("scraper", {}).get("request_timeout", 30)
        self.max_pdf_pages = config.get("scraper", {}).get("max_pdf_pages", 10)
        self.keywords = [kw.lower() for kw in config.get("scraper", {}).get("keywords", [])]
        self.respect_robots_txt = config.get("scraper", {}).get("respect_robots_txt", True)
        self.tracker = DuplicateTracker()
        self.session = requests.Session()
        self.session.headers["User-Agent"] = RATSINFO_USER_AGENT

    def _matches_keywords(self, item: "CouncilItem") -> bool:
        """Return True if item matches configured keywords, or no keywords are set."""
        if not self.keywords:
            return True
        text = f"{item.title} {item.body_text}".lower()
        return any(kw in text for kw in self.keywords)

    def detect_system(self) -> str:
        if not self.base_url:
            return "unknown"
        try:
            resp = self._fetch_page(self.base_url)
            if resp is None:
                return "unknown"
            text = str(resp)
            if "sessionnet" in text.lower() or "ko-list" in text.lower():
                return "sessionnet"
            if "allris" in text.lower() or "risinh" in text.lower():
                return "allris"
        except Exception as exc:
            logger.warning("detect_system error: %s", exc)
        return "unknown"

    def fetch_new_items(self) -> Iterator[CouncilItem]:
        if not self.base_url:
            logger.error("No ratsinfo_url configured")
            return
        if self.respect_robots_txt and not self._check_robots(self.base_url):
            logger.warning("robots.txt disallows crawling %s", self.base_url)
            return
        if not self.respect_robots_txt:
            logger.warning("robots.txt-Prüfung deaktiviert – stelle sicher, dass du zur Nutzung berechtigt bist.")
        system = self.detect_system()
        logger.info("Detected system: %s", system)
        try:
            if system == "sessionnet":
                items = self._fetch_sessionnet()
            elif system == "allris":
                items = self._fetch_allris()
            else:
                items = self._fetch_generic()
            for item in items:
                if self._matches_keywords(item):
                    yield item
                else:
                    logger.debug("Item skipped by keyword filter: %s", item.title)
        except Exception as exc:
            logger.error("fetch_new_items failed: %s", exc)

    def _fetch_and_parse(self, selectors: list, source_system: str) -> Iterator[CouncilItem]:
        soup = self._fetch_page(self.base_url)
        if soup is None:
            return
        for selector in selectors:
            for element in soup.select(selector):
                try:
                    item = self._parse_list_item(element, source_system)
                    if item and self.tracker.is_new(item.id):
                        rate_limit_sleep()
                        yield item
                except Exception as exc:
                    logger.warning("Error parsing %s item: %s", source_system, exc)

    def _fetch_sessionnet(self) -> Iterator[CouncilItem]:
        yield from self._fetch_and_parse(
            [".ko-list li", ".to-list li", ".vorl-list li"], "sessionnet"
        )

    def _fetch_allris(self) -> Iterator[CouncilItem]:
        yield from self._fetch_and_parse(
            ["#risinh tr", ".title"], "allris"
        )

    def _fetch_generic(self) -> Iterator[CouncilItem]:
        soup = self._fetch_page(self.base_url)
        if soup is None:
            return
        for a in soup.find_all("a", href=True):
            try:
                href = a["href"]
                if not any(kw in href.lower() for kw in ["vorl", "antrag", "beschluss", "tagesord"]):
                    continue
                url = urljoin(self.base_url, href)
                if not _is_safe_url(url):
                    continue
                title = a.get_text(strip=True)
                if not title:
                    continue
                item_id = self._build_item_id(url, title)
                if not self.tracker.is_new(item_id):
                    continue
                rate_limit_sleep()
                detail = self._fetch_page(url)
                body_text = detail.get_text(" ", strip=True) if detail else ""
                item = CouncilItem(
                    id=item_id,
                    title=title,
                    url=url,
                    item_type="generic",
                    date="",
                    body_text=truncate_text(body_text, 12000),
                    source_system="generic",
                )
                yield item
            except Exception as exc:
                logger.warning("Error in generic fetch: %s", exc)

    def _parse_list_item(self, element, source_system: str) -> Optional[CouncilItem]:
        a_tag = element.find("a", href=True)
        if not a_tag:
            return None
        title = a_tag.get_text(strip=True)
        if not title:
            return None
        href = a_tag["href"]
        url = urljoin(self.base_url, href) if not href.startswith("http") else href
        if not _is_safe_url(url):
            logger.warning("Skipping unsafe URL scheme: %s", url)
            return None
        item_id = self._build_item_id(url, title)
        date_tag = element.find(class_=["date", "datum"])
        date_str = date_tag.get_text(strip=True) if date_tag else ""
        detail_soup = self._fetch_page(url)
        body_text = ""
        pdf_texts = []
        if detail_soup:
            body_text = detail_soup.get_text(" ", strip=True)
            for pdf_link in detail_soup.find_all("a", href=True):
                if pdf_link["href"].lower().endswith(".pdf"):
                    pdf_url = urljoin(url, pdf_link["href"])
                    try:
                        text = self._extract_pdf_text(pdf_url, self.max_pdf_pages)
                        if text:
                            pdf_texts.append(text)
                    except Exception as exc:
                        logger.warning("PDF extraction failed %s: %s", pdf_url, exc)
        return CouncilItem(
            id=item_id,
            title=title,
            url=url,
            item_type="item",
            date=date_str,
            body_text=truncate_text(body_text, 12000),
            pdf_texts=pdf_texts,
            source_system=source_system,
        )

    def _fetch_page(self, url: str) -> Optional[BeautifulSoup]:
        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except requests.exceptions.Timeout:
            logger.warning("Timeout fetching %s", url)
        except requests.exceptions.RequestException as exc:
            logger.warning("Request error fetching %s: %s", url, exc)
        return None

    def _extract_pdf_text(self, pdf_url: str, max_pages: int) -> str:
        try:
            import pdfplumber
        except ImportError:
            logger.warning("pdfplumber not installed, skipping PDF extraction")
            return ""
        try:
            resp = self.session.get(pdf_url, timeout=self.timeout)
            resp.raise_for_status()
            with pdfplumber.open(BytesIO(resp.content)) as pdf:
                pages = pdf.pages[:max_pages]
                texts = [p.extract_text() or "" for p in pages]
            return "\n".join(texts)
        except Exception as exc:
            logger.warning("PDF extraction error %s: %s", pdf_url, exc)
            return ""

    def _build_item_id(self, url: str, title: str) -> str:
        raw = f"{url}|{title}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def _check_robots(self, url: str) -> bool:
        try:
            parsed = urlparse(url)
            robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
            rp = RobotFileParser()
            rp.set_url(robots_url)
            rp.read()
            return rp.can_fetch(RATSINFO_USER_AGENT, url)
        except Exception as exc:
            logger.warning("robots.txt check failed: %s", exc)
            return True  # Assume allowed on error
