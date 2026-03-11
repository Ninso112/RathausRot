import logging
import time
import re
from html.parser import HTMLParser

RATSINFO_USER_AGENT = "RathausRot/1.0 (Kommunalpolitik-Bot; +https://github.com/dein-user/rathausrot)"


def setup_logging(log_file: str = "rathausrot.log", level: str = "INFO") -> None:
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    root = logging.getLogger()
    root.setLevel(numeric_level)
    if root.handlers:
        root.handlers.clear()

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(formatter)
    root.addHandler(fh)

    sh = logging.StreamHandler()
    sh.setFormatter(formatter)
    root.addHandler(sh)


def chunk_html(html: str, max_bytes: int = 60000) -> list:
    """Split HTML into chunks at </p> or </li> boundaries, each ≤ max_bytes."""
    chunks = []
    current = ""
    # Split at closing block tags but keep the delimiter
    parts = re.split(r'(</p>|</li>|</h3>|<hr\s*/?>)', html)
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


def rate_limit_sleep(seconds: float = 2.0) -> None:
    time.sleep(seconds)


def truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars - 3] + "..."


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
