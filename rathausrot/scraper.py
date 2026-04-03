import hashlib
import logging
import re
from datetime import date, datetime
from io import BytesIO
from typing import Iterator, List, Optional
from urllib.robotparser import RobotFileParser
from urllib.parse import urljoin, urlparse, parse_qs

import requests
from requests.adapters import HTTPAdapter
from bs4 import BeautifulSoup

from rathausrot.utils import RATSINFO_USER_AGENT, parse_german_date, rate_limit_sleep, truncate_text
from rathausrot.models import CouncilItem, Session
from rathausrot.database import (
    DatabaseManager,
    DuplicateTracker,
    RunHistoryTracker,
    RetryQueue,
    CouncilItemStore,
    LLMCache,
)

# Re-export for backwards compatibility
__all__ = [
    "CouncilItem",
    "Session",
    "DatabaseManager",
    "DuplicateTracker",
    "RunHistoryTracker",
    "RetryQueue",
    "CouncilItemStore",
    "LLMCache",
    "RatsinfoScraper",
    "_is_safe_url",
]

logger = logging.getLogger(__name__)

_ALLOWED_SCHEMES = {"http", "https"}


def _is_safe_url(url: str) -> bool:
    return urlparse(url).scheme in _ALLOWED_SCHEMES


class RatsinfoScraper:
    def __init__(self, config: dict, city_name: str = ""):
        self.config = config
        self.city_name = city_name
        self.base_url = config.get("scraper", {}).get("ratsinfo_url", "")
        self.timeout = config.get("scraper", {}).get("request_timeout", 30)
        self.max_pdf_pages = config.get("scraper", {}).get("max_pdf_pages", 10)
        self.keywords = [
            kw.lower() for kw in config.get("scraper", {}).get("keywords", [])
        ]
        self.respect_robots_txt = config.get("scraper", {}).get(
            "respect_robots_txt", True
        )
        self.tracker = DuplicateTracker()
        self.session = requests.Session()
        self.session.headers["User-Agent"] = RATSINFO_USER_AGENT
        adapter = HTTPAdapter(
            pool_connections=10,
            pool_maxsize=20,
            max_retries=3,
        )
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self._detected_system: Optional[str] = None

    def close(self):
        """Close the HTTP session and release connection pool resources."""
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def _is_future_or_unknown_date(self, date_str: str) -> bool:
        """Return True if item date is in the future or cannot be parsed (safe default)."""
        if not date_str:
            return True
        parsed = parse_german_date(date_str)
        if parsed is None:
            return True  # Unparseable date → include to be safe
        return parsed >= date.today()

    def _matches_keywords(self, item: CouncilItem) -> bool:
        """Return True if item matches configured keywords, or no keywords are set."""
        if not self.keywords:
            return True
        text = f"{item.title} {item.body_text}".lower()
        return any(kw in text for kw in self.keywords)

    def detect_system(self) -> str:
        if self._detected_system is not None:
            return self._detected_system
        if not self.base_url:
            return "unknown"
        try:
            resp = self._fetch_page(self.base_url)
            if resp is None:
                return "unknown"
            text = str(resp)
            if "sternberg" in text.lower() or "kdvz" in text.lower() or "$SST" in text:
                self._detected_system = "sternberg"
            elif "sessionnet" in text.lower() or "ko-list" in text.lower():
                self._detected_system = "sessionnet"
            elif "allris" in text.lower() or "risinh" in text.lower():
                self._detected_system = "allris"
            else:
                self._detected_system = "unknown"
        except (requests.RequestException, ValueError, AttributeError) as exc:
            logger.warning("detect_system error: %s", exc)
            self._detected_system = "unknown"
        return self._detected_system

    def count_upcoming_items(self) -> Optional[int]:
        """Return the number of upcoming (future-dated) items if quickly determinable."""
        system = self.detect_system()
        if system == "sternberg":
            return self._count_sternberg_upcoming()
        return None

    def _count_sternberg_upcoming(self) -> Optional[int]:
        vorlagen_url = urljoin(self.base_url, "/vorlagen")
        soup = self._fetch_page(vorlagen_url)
        if soup is None:
            return None
        table = soup.find(class_="vorlagenübersicht") or soup.find(
            class_="vorlagenuebersicht"
        )
        links = (table or soup).find_all("a", href=lambda h: h and "/vorgang/?__=" in h)
        count = 0
        for a_tag in links:
            parent = a_tag.find_parent(["tr", "li", "div"])
            date_str = ""
            if parent:
                tops_link = parent.find("a", href=lambda h: h and "/tops/?__=" in h)
                if tops_link:
                    date_str = tops_link.get_text(strip=True)
            if self._is_future_or_unknown_date(date_str):
                count += 1
        return count

    def fetch_new_items(self, force: bool = False) -> Iterator[CouncilItem]:
        if not self.base_url:
            logger.error("No ratsinfo_url configured")
            return
        if self.respect_robots_txt and not self._check_robots(self.base_url):
            logger.warning("robots.txt disallows crawling %s", self.base_url)
            return
        if not self.respect_robots_txt:
            logger.warning(
                "robots.txt-Prüfung deaktiviert – stelle sicher, dass du zur Nutzung berechtigt bist."
            )
        system = self.detect_system()
        logger.info("Detected system: %s", system)
        try:
            if system == "sessionnet":
                items = self._fetch_sessionnet(force=force)
            elif system == "allris":
                items = self._fetch_allris(force=force)
            elif system == "sternberg":
                items = self._fetch_sternberg(force=force)
            else:
                items = self._fetch_generic(force=force)
            for item in items:
                if not self._is_future_or_unknown_date(item.date):
                    logger.debug(
                        "Item skipped (date in past): %s (%s)", item.title, item.date
                    )
                    continue
                if self._matches_keywords(item):
                    yield item
                else:
                    logger.debug("Item skipped by keyword filter: %s", item.title)
        except Exception as exc:
            logger.error("fetch_new_items failed: %s", exc)

    def _fetch_and_parse(
        self, selectors: list, source_system: str, force: bool = False
    ) -> Iterator[CouncilItem]:
        soup = self._fetch_page(self.base_url)
        if soup is None:
            return
        for selector in selectors:
            for element in soup.select(selector):
                try:
                    item = self._parse_list_item(element, source_system)
                    if item and (force or self.tracker.is_new(item.id)):
                        if not item.body_text and not item.pdf_urls:
                            logger.debug("Item skipped (no content): %s", item.title)
                            continue
                        rate_limit_sleep()
                        yield item
                except Exception as exc:
                    logger.warning("Error parsing %s item: %s", source_system, exc)

    def _fetch_sessionnet(self, force: bool = False) -> Iterator[CouncilItem]:
        yield from self._fetch_and_parse(
            [".ko-list li", ".to-list li", ".vorl-list li"], "sessionnet", force=force
        )

    def _fetch_allris(self, force: bool = False) -> Iterator[CouncilItem]:
        yield from self._fetch_and_parse(
            ["#risinh tr", ".title"], "allris", force=force
        )

    @staticmethod
    def _sternberg_canonical_id(url: str) -> str:
        """Extract the __= parameter from a Sternberg URL as canonical item identifier."""
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        dunder = params.get("__", [None])[0]
        return dunder if dunder else url

    def _fetch_sternberg(self, force: bool = False) -> Iterator[CouncilItem]:
        vorlagen_url = urljoin(self.base_url, "/vorlagen")
        soup = self._fetch_page(vorlagen_url)
        if soup is None:
            return
        table = soup.find(class_="vorlagenübersicht") or soup.find(
            class_="vorlagenuebersicht"
        )
        if table is None:
            # Fallback: search for vorgang links directly
            rows = soup.find_all("a", href=lambda h: h and "/vorgang/?__=" in h)
        else:
            rows = table.find_all("a", href=lambda h: h and "/vorgang/?__=" in h)
        seen_canonical: set = set()
        for a_tag in rows:
            try:
                href = a_tag["href"]
                url = urljoin(self.base_url, href)
                if not _is_safe_url(url):
                    continue
                canonical = self._sternberg_canonical_id(url)
                if canonical in seen_canonical:
                    logger.debug("Sternberg duplicate skipped (same __= id): %s", url)
                    continue
                seen_canonical.add(canonical)
                title = a_tag.get_text(strip=True)
                if not title:
                    continue
                # Try to find date from nearby tops link
                parent = a_tag.find_parent(["tr", "li", "div"])
                date_str = ""
                if parent:
                    tops_link = parent.find("a", href=lambda h: h and "/tops/?__=" in h)
                    if tops_link:
                        date_str = tops_link.get_text(strip=True)
                item_id = self._build_item_id(url, title)
                if not force and not self.tracker.is_new(item_id):
                    logger.debug("Skipping known Sternberg item: %s", title)
                    continue
                # Skip detail fetch for past items early (saves HTTP requests)
                if date_str and not self._is_future_or_unknown_date(date_str):
                    logger.debug(
                        "Sternberg item skipped early (past date): %s (%s)",
                        title,
                        date_str,
                    )
                    continue
                rate_limit_sleep()
                item = self._parse_sternberg_item(item_id, title, url, date_str)
                if item:
                    yield item
            except Exception as exc:
                logger.warning("Error in Sternberg fetch: %s", exc)

    def _parse_sternberg_item(
        self, item_id: str, title: str, url: str, date_str: str
    ) -> Optional[CouncilItem]:
        detail_soup = self._fetch_page(url)
        body_text = ""
        pdf_texts = []
        pdf_urls = []
        if detail_soup:
            body_text = detail_soup.get_text(" ", strip=True)
            for pdf_link in detail_soup.find_all(
                "a", href=lambda h: h and "/sdnetrim/" in h
            ):
                pdf_url = urljoin(url, pdf_link["href"])
                if not _is_safe_url(pdf_url):
                    continue
                pdf_urls.append(pdf_url)
                try:
                    text = self._extract_pdf_text(pdf_url, self.max_pdf_pages)
                    if text:
                        pdf_texts.append(text)
                except Exception as exc:
                    logger.warning(
                        "Sternberg PDF extraction failed %s: %s", pdf_url, exc
                    )
        return CouncilItem(
            id=item_id,
            title=title,
            url=url,
            item_type="vorlage",
            date=date_str,
            body_text=truncate_text(body_text, 12000),
            pdf_texts=pdf_texts,
            pdf_urls=pdf_urls,
            source_system="sternberg",
            city_name=self.city_name,
        )

    def _fetch_generic(self, force: bool = False) -> Iterator[CouncilItem]:
        soup = self._fetch_page(self.base_url)
        if soup is None:
            return
        for a in soup.find_all("a", href=True):
            try:
                href = a["href"]
                if not any(
                    kw in href.lower()
                    for kw in ["vorl", "antrag", "beschluss", "tagesord"]
                ):
                    continue
                url = urljoin(self.base_url, href)
                if not _is_safe_url(url):
                    continue
                title = a.get_text(strip=True)
                if not title:
                    continue
                item_id = self._build_item_id(url, title)
                if not force and not self.tracker.is_new(item_id):
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
                    city_name=self.city_name,
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
        pdf_urls = []
        if detail_soup:
            body_text = detail_soup.get_text(" ", strip=True)
            for pdf_link in detail_soup.find_all("a", href=True):
                if pdf_link["href"].lower().endswith(".pdf"):
                    pdf_url = urljoin(url, pdf_link["href"])
                    pdf_urls.append(pdf_url)
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
            pdf_urls=pdf_urls,
            source_system=source_system,
            city_name=self.city_name,
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
            with self.session.get(pdf_url, timeout=self.timeout, stream=True) as resp:
                resp.raise_for_status()
                content_length = resp.headers.get("content-length")
                if content_length and int(content_length) > 50 * 1024 * 1024:
                    logger.warning("PDF too large (>50MB), skipping: %s", pdf_url)
                    return ""
                pdf_data = resp.content
            with pdfplumber.open(BytesIO(pdf_data)) as pdf:
                pages = pdf.pages[:max_pages]
                texts = [p.extract_text() or "" for p in pages]
            return "\n".join(texts)
        except Exception as exc:
            logger.warning("PDF extraction error %s: %s", pdf_url, exc)
            return ""

    def _build_item_id(self, url: str, title: str) -> str:
        raw = f"{url}|{title}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def fetch_sessions(self) -> List[Session]:
        """Fetch session list from the council system. Returns new sessions for announcement."""
        if not self.base_url:
            return []
        system = self.detect_system()
        try:
            if system == "sternberg":
                return self._fetch_sessions_sternberg()
            elif system == "sessionnet":
                return self._fetch_sessions_sessionnet()
            else:
                return []
        except Exception as exc:
            logger.warning("fetch_sessions failed: %s", exc)
            return []

    def _fetch_sessions_sternberg(self) -> List[Session]:
        sitzungen_url = urljoin(self.base_url, "/sitzungen")
        soup = self._fetch_page(sitzungen_url)
        if soup is None:
            return []
        sessions = []
        for a in soup.find_all("a", href=lambda h: h and "/tops/?__=" in h):
            try:
                href = a["href"]
                url = urljoin(self.base_url, href)
                if not _is_safe_url(url):
                    continue
                title = a.get_text(strip=True)
                if not title:
                    continue
                parent = a.find_parent(["tr", "li", "div"])
                date_str = ""
                body_name = ""
                if parent:
                    text = parent.get_text(" ", strip=True)
                    date_match = re.search(r"\d{2}\.\d{2}\.\d{4}", text)
                    if date_match:
                        date_str = date_match.group(0)
                session_id = self._build_item_id(url, title)
                sessions.append(
                    Session(
                        id=session_id,
                        title=title,
                        date=date_str,
                        url=url,
                        body_name=body_name,
                    )
                )
            except Exception as exc:
                logger.warning("Error parsing Sternberg session: %s", exc)
        return sessions

    def _fetch_sessions_sessionnet(self) -> List[Session]:
        soup = self._fetch_page(self.base_url)
        if soup is None:
            return []
        sessions = []
        for a in soup.find_all(
            "a",
            href=lambda h: (
                h
                and any(
                    kw in h.lower() for kw in ["sitzung", "session", "tops", "gremien"]
                )
            ),
        ):
            try:
                href = a["href"]
                url = urljoin(self.base_url, href)
                if not _is_safe_url(url):
                    continue
                title = a.get_text(strip=True)
                if not title or len(title) < 5:
                    continue
                session_id = self._build_item_id(url, title)
                sessions.append(
                    Session(
                        id=session_id,
                        title=title,
                        date="",
                        url=url,
                    )
                )
            except Exception as exc:
                logger.warning("Error parsing SessionNet session: %s", exc)
        return sessions

    def _check_robots(self, url: str) -> bool:
        try:
            parsed = urlparse(url)
            robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
            resp = self.session.get(robots_url, timeout=self.timeout)
            if resp.status_code == 404:
                return True  # No robots.txt → everything allowed
            resp.raise_for_status()
            rp = RobotFileParser()
            rp.parse(resp.text.splitlines())
            return rp.can_fetch(RATSINFO_USER_AGENT, url)
        except requests.RequestException as exc:
            logger.warning("robots.txt fetch failed (assuming allowed): %s", exc)
            return True
        except (ValueError, TypeError) as exc:
            logger.warning("robots.txt parse error (blocking to be safe): %s", exc)
            return False
