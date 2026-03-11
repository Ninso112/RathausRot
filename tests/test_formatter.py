import pytest
from rathausrot.formatter import MatrixFormatter, VERDICT_EMOJI
from rathausrot.scraper import CouncilItem
from rathausrot.llm_client import LLMResult
from rathausrot.utils import chunk_html


def make_item(title="Test TOP", url="https://example.com/item/1"):
    return CouncilItem(
        id="abc123",
        title=title,
        url=url,
        item_type="item",
        date="2024-01-15",
        body_text="Test body text",
        source_system="sessionnet",
    )


def make_result(verdict="Zustimmung"):
    return LLMResult(
        summary="Eine kurze Zusammenfassung.",
        key_points=["Punkt 1", "Punkt 2"],
        verdict=verdict,
        verdict_reason="Weil es gut ist.",
        relevance_score=4,
    )


def test_format_item_contains_title():
    formatter = MatrixFormatter()
    item = make_item(title="Wichtiger Tagesordnungspunkt")
    result = make_result()
    html = formatter.format_item(item, result)
    assert "Wichtiger Tagesordnungspunkt" in html


def test_format_item_verdict_emoji():
    formatter = MatrixFormatter()
    item = make_item()
    for verdict, emoji in VERDICT_EMOJI.items():
        result = make_result(verdict=verdict)
        html = formatter.format_item(item, result)
        assert emoji in html
        assert verdict in html


def test_chunk_html_splits_large_input():
    # Generate ~130KB of HTML
    large_html = ""
    for i in range(500):
        large_html += f"<p>Dies ist Paragraph Nummer {i} mit etwas mehr Text um die Größe zu erhöhen. " \
                      f"Mehr Inhalt hier für Paragraph {i}.</p>\n"

    chunks = chunk_html(large_html, max_bytes=60000)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk.encode("utf-8")) <= 65535


def test_footer_in_every_chunk():
    formatter = MatrixFormatter()
    items = []
    for i in range(20):
        item = make_item(title=f"TOP {i}", url=f"https://example.com/item/{i}")
        result = make_result()
        items.append((item, result))

    chunks = formatter.format_weekly_report(items, kw=42, year=2024)
    for chunk in chunks:
        assert "automatisch generierte Prognosen" in chunk


def test_format_item_absolute_url():
    formatter = MatrixFormatter()
    item = make_item(url="https://ratsinfo.example.de/bi/vo020.asp?VOLFDNR=1234")
    result = make_result()
    html = formatter.format_item(item, result)
    # URL in href must be absolute (start with https://)
    import re
    hrefs = re.findall(r'href="([^"]+)"', html)
    for href in hrefs:
        assert href.startswith("http"), f"Non-absolute URL found: {href}"
