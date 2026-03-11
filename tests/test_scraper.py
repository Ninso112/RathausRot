import os
import sqlite3
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from rathausrot.scraper import CouncilItem, DuplicateTracker, RatsinfoScraper


def test_build_item_id_is_deterministic():
    config = {"scraper": {"ratsinfo_url": "", "max_pdf_pages": 10, "request_timeout": 30}, "bot": {}}
    scraper = RatsinfoScraper.__new__(RatsinfoScraper)
    scraper.base_url = "http://example.com"
    scraper.timeout = 30
    scraper.max_pdf_pages = 10

    url = "http://example.com/item/123"
    title = "Test Tagesordnungspunkt"
    id1 = scraper._build_item_id(url, title)
    id2 = scraper._build_item_id(url, title)
    assert id1 == id2
    assert len(id1) == 16


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


def test_fetch_page_returns_none_on_timeout():
    import requests
    config = {"scraper": {"ratsinfo_url": "http://example.com", "max_pdf_pages": 10, "request_timeout": 30}, "bot": {}}
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        with patch("rathausrot.scraper.DuplicateTracker") as MockTracker:
            MockTracker.return_value = MagicMock()
            scraper = RatsinfoScraper(config)
            scraper.tracker = MockTracker.return_value

        with patch.object(scraper.session, "get", side_effect=requests.exceptions.Timeout):
            result = scraper._fetch_page("http://example.com/timeout")
        assert result is None
    finally:
        os.unlink(db_path)


def test_detect_system_sessionnet():
    config = {"scraper": {"ratsinfo_url": "http://example.com", "max_pdf_pages": 10, "request_timeout": 30}, "bot": {}}
    with patch("rathausrot.scraper.DuplicateTracker"):
        scraper = RatsinfoScraper(config)
    from bs4 import BeautifulSoup
    mock_soup = BeautifulSoup('<div class="ko-list"><li>item</li></div>', "html.parser")
    with patch.object(scraper, "_fetch_page", return_value=mock_soup):
        result = scraper.detect_system()
    assert result == "sessionnet"


def test_extract_pdf_text_truncates_to_max_pages():
    config = {"scraper": {"ratsinfo_url": "http://example.com", "max_pdf_pages": 2, "request_timeout": 30}, "bot": {}}
    with patch("rathausrot.scraper.DuplicateTracker"):
        scraper = RatsinfoScraper(config)

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
