import logging
import re
import time
from collections import deque
from datetime import date, datetime
from html.parser import HTMLParser
from logging.handlers import RotatingFileHandler

RATSINFO_USER_AGENT = (
    "RathausRot/1.0 (Kommunalpolitik-Bot; +https://github.com/Ninso112/RathausRot)"
)


class MemoryLogHandler(logging.Handler):
    """Ring-buffer handler that keeps the last max_entries log entries in RAM."""

    def __init__(self, max_entries: int = 2000):
        super().__init__()
        self._buffer: deque = deque(maxlen=max_entries)

    def emit(self, record):
        self._buffer.append(self.format(record))

    def get_logs(self, count: int = 50, level: str | None = None) -> list:
        """Return the last `count` entries, optionally filtered by level."""
        entries = list(self._buffer)
        if level:
            entries = [e for e in entries if f"[{level.upper()}]" in e]
        return entries[-count:]


_memory_handler: MemoryLogHandler | None = None


def setup_logging(
    log_file: str = "rathausrot.log", level: str = "INFO"
) -> MemoryLogHandler:
    global _memory_handler
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    root = logging.getLogger()
    root.setLevel(numeric_level)
    if root.handlers:
        root.handlers.clear()

    fh = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(formatter)
    root.addHandler(fh)

    sh = logging.StreamHandler()
    sh.setFormatter(formatter)
    root.addHandler(sh)

    _memory_handler = MemoryLogHandler(max_entries=2000)
    _memory_handler.setFormatter(formatter)
    root.addHandler(_memory_handler)

    return _memory_handler


def get_memory_handler() -> MemoryLogHandler | None:
    return _memory_handler


def chunk_html(html: str, max_bytes: int = 60000) -> list:
    """Split HTML into chunks at </p> or </li> boundaries, each <= max_bytes."""
    if not html:
        return []
    chunks = []
    current = ""
    # Split at closing block tags but keep the delimiter
    parts = re.split(r"(</p>|</li>|</h3>|<hr\s*/?>)", html)
    for part in parts:
        candidate = current + part
        if len(candidate.encode("utf-8")) > max_bytes and current:
            chunks.append(current)
            current = part
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def parse_german_date(date_str: str) -> date | None:
    """Parse a German date string (e.g. 'Mi, 15.01.2024 10:00 Uhr') into a date object."""
    if not date_str:
        return None
    cleaned = re.sub(r"^[A-Za-z\u00c0-\u024f]+,\s*", "", date_str.strip())
    for fmt in ("%d.%m.%Y %H:%M Uhr", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def rate_limit_sleep(seconds: float = 2.0) -> None:
    time.sleep(seconds)


def truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


class _HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.result = []

    def handle_data(self, d):
        self.result.append(d)

    def get_text(self):
        return "".join(self.result)


def strip_html(html: str) -> str:
    stripper = _HTMLStripper()
    stripper.feed(html)
    return stripper.get_text()
