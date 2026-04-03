import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
import requests

from rathausrot.scraper import (
    CouncilItem,
    DuplicateTracker,
    RunHistoryTracker,
    LLMCache,
    RetryQueue,
    RatsinfoScraper,
    _is_safe_url,
)


# ------------------------------------------------------------------ #
# _is_safe_url
# ------------------------------------------------------------------ #


def test_is_safe_url_accepts_http():
    assert _is_safe_url("http://example.com") is True


def test_is_safe_url_accepts_https():
    assert _is_safe_url("https://example.com") is True


def test_is_safe_url_rejects_javascript():
    assert _is_safe_url("javascript:alert(1)") is False


def test_is_safe_url_rejects_data():
    assert _is_safe_url("data:text/html,<h1>hi</h1>") is False


def test_is_safe_url_rejects_file():
    assert _is_safe_url("file:///etc/passwd") is False


def test_is_safe_url_rejects_ftp():
    assert _is_safe_url("ftp://example.com") is False


# ------------------------------------------------------------------ #
# DuplicateTracker
# ------------------------------------------------------------------ #


def test_duplicate_tracker_roundtrip():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        tracker = DuplicateTracker(db_path)
        item_id = "abc123def456789"
        assert tracker.is_new(item_id) is True
        tracker.mark_processed(item_id)
        assert tracker.is_new(item_id) is False
    finally:
        os.unlink(db_path)


def test_duplicate_tracker_mark_processed_idempotent():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        tracker = DuplicateTracker(db_path)
        tracker.mark_processed("id1")
        tracker.mark_processed("id1")  # should not raise
        assert tracker.is_new("id1") is False
    finally:
        os.unlink(db_path)


# ------------------------------------------------------------------ #
# RunHistoryTracker
# ------------------------------------------------------------------ #


def test_run_history_record_and_get():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        tracker = RunHistoryTracker(db_path)
        tracker.record_run(5, True)
        tracker.record_run(0, False, "some error")
        recent = tracker.get_recent(10)
        assert len(recent) == 2
        # Check both entries exist (order depends on timestamp precision)
        successes = [e for e in recent if e["success"]]
        failures = [e for e in recent if not e["success"]]
        assert len(successes) == 1
        assert successes[0]["item_count"] == 5
        assert len(failures) == 1
        assert failures[0]["error_msg"] == "some error"
    finally:
        os.unlink(db_path)


def test_run_history_limit():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        tracker = RunHistoryTracker(db_path)
        for i in range(20):
            tracker.record_run(i, True)
        recent = tracker.get_recent(5)
        assert len(recent) == 5
    finally:
        os.unlink(db_path)


def test_run_history_empty():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        tracker = RunHistoryTracker(db_path)
        assert tracker.get_recent() == []
    finally:
        os.unlink(db_path)


# ------------------------------------------------------------------ #
# LLMCache
# ------------------------------------------------------------------ #


def test_llm_cache_put_and_get():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        cache = LLMCache(db_path)
        from rathausrot.llm_client import LLMResult

        result = LLMResult(
            summary="test",
            key_points=["a"],
            verdict="Zustimmung",
            verdict_reason="good",
            relevance_score=4,
        )
        cache.put("item1", result)
        cached = cache.get("item1")
        assert cached is not None
        assert cached["summary"] == "test"
        assert cached["relevance_score"] == 4
    finally:
        os.unlink(db_path)


def test_llm_cache_miss():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        cache = LLMCache(db_path)
        assert cache.get("nonexistent") is None
    finally:
        os.unlink(db_path)


def test_llm_cache_overwrite():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        cache = LLMCache(db_path)
        from rathausrot.llm_client import LLMResult

        r1 = LLMResult(summary="old")
        r2 = LLMResult(summary="new")
        cache.put("item1", r1)
        cache.put("item1", r2)
        cached = cache.get("item1")
        assert cached["summary"] == "new"
    finally:
        os.unlink(db_path)


# ------------------------------------------------------------------ #
# RetryQueue
# ------------------------------------------------------------------ #


def test_retry_queue_add_and_get():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        queue = RetryQueue(db_path)
        item = CouncilItem(
            id="r1",
            title="Retry",
            url="http://x",
            item_type="item",
            date="",
            body_text="body",
            source_system="test",
        )
        queue.add(item)
        pending = queue.get_pending()
        assert len(pending) == 1
        assert pending[0].id == "r1"
    finally:
        os.unlink(db_path)


def test_retry_queue_remove():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        queue = RetryQueue(db_path)
        item = CouncilItem(
            id="r2",
            title="T",
            url="http://x",
            item_type="item",
            date="",
            body_text="",
            source_system="test",
        )
        queue.add(item)
        queue.remove("r2")
        assert queue.get_pending() == []
    finally:
        os.unlink(db_path)


def test_retry_queue_max_attempts():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        queue = RetryQueue(db_path)
        item = CouncilItem(
            id="r3",
            title="T",
            url="http://x",
            item_type="item",
            date="",
            body_text="",
            source_system="test",
        )
        for _ in range(5):
            queue.add(item)
        # Default max_attempts=3, should be filtered out
        pending = queue.get_pending(max_attempts=3)
        assert len(pending) == 0
    finally:
        os.unlink(db_path)


# ------------------------------------------------------------------ #
# RatsinfoScraper
# ------------------------------------------------------------------ #


def _make_scraper(config_overrides=None):
    config = {
        "scraper": {
            "ratsinfo_url": "http://example.com",
            "max_pdf_pages": 10,
            "request_timeout": 30,
            "keywords": [],
        },
        "bot": {},
    }
    if config_overrides:
        for k, v in config_overrides.items():
            if isinstance(v, dict) and k in config:
                config[k].update(v)
            else:
                config[k] = v
    with patch("rathausrot.scraper.DuplicateTracker"):
        scraper = RatsinfoScraper(config)
    return scraper


def test_build_item_id_is_deterministic():
    scraper = _make_scraper()
    url = "http://example.com/item/123"
    title = "Test Tagesordnungspunkt"
    id1 = scraper._build_item_id(url, title)
    id2 = scraper._build_item_id(url, title)
    assert id1 == id2
    assert len(id1) == 16


def test_build_item_id_different_for_different_inputs():
    scraper = _make_scraper()
    id1 = scraper._build_item_id("http://a", "title")
    id2 = scraper._build_item_id("http://b", "title")
    assert id1 != id2


def test_fetch_page_returns_none_on_timeout():
    scraper = _make_scraper()
    with patch.object(scraper.session, "get", side_effect=requests.exceptions.Timeout):
        result = scraper._fetch_page("http://example.com/timeout")
    assert result is None


def test_fetch_page_returns_none_on_request_error():
    scraper = _make_scraper()
    with patch.object(
        scraper.session, "get", side_effect=requests.exceptions.ConnectionError
    ):
        result = scraper._fetch_page("http://example.com/error")
    assert result is None


def test_fetch_page_success():
    scraper = _make_scraper()
    mock_resp = MagicMock()
    mock_resp.text = "<html><body>Hello</body></html>"
    mock_resp.raise_for_status = MagicMock()
    with patch.object(scraper.session, "get", return_value=mock_resp):
        result = scraper._fetch_page("http://example.com")
    assert result is not None
    assert "Hello" in result.get_text()


def test_detect_system_sessionnet():
    scraper = _make_scraper()
    from bs4 import BeautifulSoup

    mock_soup = BeautifulSoup('<div class="ko-list"><li>item</li></div>', "html.parser")
    with patch.object(scraper, "_fetch_page", return_value=mock_soup):
        result = scraper.detect_system()
    assert result == "sessionnet"


def test_detect_system_allris():
    scraper = _make_scraper()
    from bs4 import BeautifulSoup

    mock_soup = BeautifulSoup('<div id="risinh"><tr>item</tr></div>', "html.parser")
    with patch.object(scraper, "_fetch_page", return_value=mock_soup):
        result = scraper.detect_system()
    assert result == "allris"


def test_detect_system_unknown():
    scraper = _make_scraper()
    from bs4 import BeautifulSoup

    mock_soup = BeautifulSoup("<div>nothing special</div>", "html.parser")
    with patch.object(scraper, "_fetch_page", return_value=mock_soup):
        result = scraper.detect_system()
    assert result == "unknown"


def test_detect_system_no_base_url():
    scraper = _make_scraper({"scraper": {"ratsinfo_url": ""}})
    assert scraper.detect_system() == "unknown"


def test_detect_system_fetch_fails():
    scraper = _make_scraper()
    with patch.object(scraper, "_fetch_page", return_value=None):
        assert scraper.detect_system() == "unknown"


def test_matches_keywords_no_keywords():
    scraper = _make_scraper()
    item = CouncilItem(
        id="x",
        title="Anything",
        url="http://x",
        item_type="item",
        date="",
        body_text="body",
        source_system="test",
    )
    assert scraper._matches_keywords(item) is True


def test_matches_keywords_match():
    scraper = _make_scraper({"scraper": {"keywords": ["haushalt", "schule"]}})
    item = CouncilItem(
        id="x",
        title="Haushaltsentwurf 2024",
        url="http://x",
        item_type="item",
        date="",
        body_text="",
        source_system="test",
    )
    assert scraper._matches_keywords(item) is True


def test_matches_keywords_no_match():
    scraper = _make_scraper({"scraper": {"keywords": ["haushalt", "schule"]}})
    item = CouncilItem(
        id="x",
        title="Straßenbau",
        url="http://x",
        item_type="item",
        date="",
        body_text="Brückenreparatur",
        source_system="test",
    )
    assert scraper._matches_keywords(item) is False


def test_matches_keywords_case_insensitive():
    scraper = _make_scraper({"scraper": {"keywords": ["Haushalt"]}})
    item = CouncilItem(
        id="x",
        title="HAUSHALT 2024",
        url="http://x",
        item_type="item",
        date="",
        body_text="",
        source_system="test",
    )
    assert scraper._matches_keywords(item) is True


def test_fetch_new_items_no_base_url():
    scraper = _make_scraper({"scraper": {"ratsinfo_url": ""}})
    items = list(scraper.fetch_new_items())
    assert items == []


def test_fetch_new_items_robots_blocked():
    scraper = _make_scraper()
    with patch.object(scraper, "_check_robots", return_value=False):
        items = list(scraper.fetch_new_items())
    assert items == []


def test_fetch_new_items_with_keyword_filter():
    scraper = _make_scraper({"scraper": {"keywords": ["haushalt"]}})
    item_match = CouncilItem(
        id="m1",
        title="Haushalt",
        url="http://x",
        item_type="item",
        date="",
        body_text="",
        source_system="test",
    )
    item_skip = CouncilItem(
        id="m2",
        title="Straße",
        url="http://y",
        item_type="item",
        date="",
        body_text="",
        source_system="test",
    )
    with (
        patch.object(scraper, "_check_robots", return_value=True),
        patch.object(scraper, "detect_system", return_value="unknown"),
        patch.object(
            scraper, "_fetch_generic", return_value=iter([item_match, item_skip])
        ),
    ):
        items = list(scraper.fetch_new_items())
    assert len(items) == 1
    assert items[0].id == "m1"


def test_parse_list_item_no_link():
    scraper = _make_scraper()
    from bs4 import BeautifulSoup

    element = BeautifulSoup("<li>No link here</li>", "html.parser").li
    result = scraper._parse_list_item(element, "test")
    assert result is None


def test_parse_list_item_empty_title():
    scraper = _make_scraper()
    from bs4 import BeautifulSoup

    element = BeautifulSoup('<li><a href="http://x">  </a></li>', "html.parser").li
    result = scraper._parse_list_item(element, "test")
    assert result is None


def test_parse_list_item_unsafe_url():
    scraper = _make_scraper()
    from bs4 import BeautifulSoup

    element = BeautifulSoup(
        '<li><a href="javascript:alert(1)">Click</a></li>', "html.parser"
    ).li
    result = scraper._parse_list_item(element, "test")
    assert result is None


def test_parse_list_item_success():
    scraper = _make_scraper()
    from bs4 import BeautifulSoup

    html = '<li><a href="http://example.com/item">Test Title</a><span class="date">2024-01-15</span></li>'
    element = BeautifulSoup(html, "html.parser").li
    detail_soup = BeautifulSoup("<html><body>Detail text</body></html>", "html.parser")
    with patch.object(scraper, "_fetch_page", return_value=detail_soup):
        result = scraper._parse_list_item(element, "sessionnet")
    assert result is not None
    assert result.title == "Test Title"
    assert result.date == "2024-01-15"
    assert "Detail text" in result.body_text


def test_parse_list_item_with_pdf():
    scraper = _make_scraper()
    from bs4 import BeautifulSoup

    html = '<li><a href="http://example.com/item">Title</a></li>'
    element = BeautifulSoup(html, "html.parser").li
    detail_html = '<html><body>Text <a href="doc.pdf">PDF</a></body></html>'
    detail_soup = BeautifulSoup(detail_html, "html.parser")
    with (
        patch.object(scraper, "_fetch_page", return_value=detail_soup),
        patch.object(scraper, "_extract_pdf_text", return_value="PDF content"),
    ):
        result = scraper._parse_list_item(element, "test")
    assert result is not None
    assert "PDF content" in result.pdf_texts


def test_fetch_and_parse_no_soup():
    scraper = _make_scraper()
    with patch.object(scraper, "_fetch_page", return_value=None):
        items = list(scraper._fetch_and_parse([".some-class"], "test"))
    assert items == []


def test_fetch_generic_no_soup():
    scraper = _make_scraper()
    with patch.object(scraper, "_fetch_page", return_value=None):
        items = list(scraper._fetch_generic())
    assert items == []


def test_fetch_generic_filters_irrelevant_links():
    scraper = _make_scraper()
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(
        '<html><a href="/about">About</a><a href="/vorlage/1">Vorlage 1</a></html>',
        "html.parser",
    )
    scraper.tracker.is_new = MagicMock(return_value=True)
    detail = BeautifulSoup("<html><body>Detail</body></html>", "html.parser")

    def fake_fetch(url):
        if url == scraper.base_url:
            return soup
        return detail

    with (
        patch.object(scraper, "_fetch_page", side_effect=fake_fetch),
        patch("rathausrot.scraper.rate_limit_sleep"),
    ):
        items = list(scraper._fetch_generic())
    assert len(items) == 1
    assert items[0].title == "Vorlage 1"


def test_fetch_generic_skips_unsafe_urls():
    scraper = _make_scraper()
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(
        '<html><a href="javascript:alert(1)">vorlage</a></html>', "html.parser"
    )
    with patch.object(scraper, "_fetch_page", return_value=soup):
        items = list(scraper._fetch_generic())
    assert items == []


def test_fetch_generic_skips_duplicates():
    scraper = _make_scraper()
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(
        '<html><a href="/vorlage/1">Vorlage 1</a></html>', "html.parser"
    )
    scraper.tracker.is_new = MagicMock(return_value=False)
    with patch.object(scraper, "_fetch_page", return_value=soup):
        items = list(scraper._fetch_generic())
    assert items == []


def test_check_robots_allows_on_error():
    scraper = _make_scraper()
    with patch("rathausrot.scraper.RobotFileParser") as MockRP:
        MockRP.return_value.read.side_effect = Exception("network error")
        assert scraper._check_robots("http://example.com") is True


def test_extract_pdf_text_no_pdfplumber():
    scraper = _make_scraper()
    with patch.dict("sys.modules", {"pdfplumber": None}):
        # This should handle ImportError gracefully
        result = scraper._extract_pdf_text("http://example.com/doc.pdf", 10)
    # We can't easily force ImportError in already-imported module, but let's test with mock
    assert isinstance(result, str)


def test_extract_pdf_text_truncates_to_max_pages():
    pdfplumber = pytest.importorskip("pdfplumber")
    scraper = _make_scraper()

    mock_page1 = MagicMock()
    mock_page1.extract_text.return_value = "Page 1 content"
    mock_page2 = MagicMock()
    mock_page2.extract_text.return_value = "Page 2 content"
    mock_page3 = MagicMock()
    mock_page3.extract_text.return_value = "Page 3 content"

    mock_pdf = MagicMock()
    mock_pdf.pages = [mock_page1, mock_page2, mock_page3]
    mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
    mock_pdf.__exit__ = MagicMock(return_value=False)

    mock_response = MagicMock()
    mock_response.content = b"fake pdf content"
    mock_response.raise_for_status = MagicMock()

    with patch.object(scraper.session, "get", return_value=mock_response):
        with patch("pdfplumber.open", return_value=mock_pdf):
            text = scraper._extract_pdf_text("http://example.com/doc.pdf", max_pages=2)

    assert "Page 3 content" not in text
    assert "Page 1 content" in text
