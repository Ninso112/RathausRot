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


def test_single_item_report_contains_disclaimer():
    formatter = MatrixFormatter()
    item = make_item()
    result = make_result()
    chunks = formatter.format_single_item_report(item, result, source_url="https://example.com")
    combined = "".join(chunks)
    assert "automatisch generierte Prognosen" in combined


def test_format_item_xss_in_title():
    formatter = MatrixFormatter()
    item = make_item(title='<script>alert("xss")</script>', url="https://example.com/safe")
    result = make_result()
    html = formatter.format_item(item, result)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_format_item_xss_in_url():
    formatter = MatrixFormatter()
    item = make_item(title="Safe Title", url='https://example.com/"><script>alert(1)</script>')
    result = make_result()
    html = formatter.format_item(item, result)
    assert "<script>" not in html


def test_format_item_xss_in_llm_output():
    formatter = MatrixFormatter()
    item = make_item()
    result = LLMResult(
        summary='<img src=x onerror=alert(1)>',
        key_points=['<script>xss</script>'],
        verdict='<b>Zustimmung</b>',
        verdict_reason='<a href="javascript:alert(1)">click</a>',
        relevance_score=3,
    )
    html = formatter.format_item(item, result)
    # Ensure raw tags are escaped (not rendered as HTML)
    assert "<img src=" not in html
    assert "&lt;img" in html
    assert "<script>xss</script>" not in html
    assert "&lt;script&gt;" in html


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
