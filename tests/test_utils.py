import logging
import os
import tempfile

import pytest

from rathausrot.utils import chunk_html, truncate_text, strip_html, MemoryLogHandler, setup_logging, get_memory_handler


class TestChunkHtml:
    def test_small_input_single_chunk(self):
        html = "<p>Hello</p>"
        chunks = chunk_html(html)
        assert len(chunks) == 1
        assert chunks[0] == html

    def test_splits_at_tag_boundaries(self):
        # Create content just over max_bytes
        part = "<p>" + "x" * 100 + "</p>"
        html = part * 10
        chunks = chunk_html(html, max_bytes=500)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk.encode("utf-8")) <= 600  # some tolerance

    def test_empty_input(self):
        assert chunk_html("") == []

    def test_single_large_element(self):
        # Single element larger than max_bytes - can't split further
        html = "<p>" + "x" * 1000 + "</p>"
        chunks = chunk_html(html, max_bytes=500)
        assert len(chunks) >= 1

    def test_unicode_handling(self):
        # German umlauts take more bytes in UTF-8
        html = "<p>" + "ä" * 200 + "</p>"
        chunks = chunk_html(html, max_bytes=300)
        assert len(chunks) >= 1


class TestTruncateText:
    def test_short_text_unchanged(self):
        assert truncate_text("hello", 10) == "hello"

    def test_exact_length_unchanged(self):
        assert truncate_text("hello", 5) == "hello"

    def test_truncated_with_ellipsis(self):
        result = truncate_text("hello world", 8)
        assert result == "hello..."
        assert len(result) == 8

    def test_very_short_max(self):
        result = truncate_text("hello", 3)
        assert len(result) == 3


class TestStripHtml:
    def test_simple_tags(self):
        assert strip_html("<p>hello</p>") == "hello"

    def test_nested_tags(self):
        assert strip_html("<div><p><b>bold</b> text</p></div>") == "bold text"

    def test_no_tags(self):
        assert strip_html("plain text") == "plain text"

    def test_entities_preserved(self):
        result = strip_html("<p>a &amp; b</p>")
        assert "a" in result and "b" in result


class TestSetupLogging:
    def test_setup_logging_returns_memory_handler(self, tmp_path):
        log_file = str(tmp_path / "test.log")
        handler = setup_logging(log_file=log_file, level="DEBUG")
        assert handler is not None
        assert isinstance(handler, MemoryLogHandler)

    def test_setup_logging_creates_file(self, tmp_path):
        log_file = str(tmp_path / "test.log")
        setup_logging(log_file=log_file)
        logger = logging.getLogger("test_setup")
        logger.info("test message")
        assert os.path.exists(log_file)

    def test_get_memory_handler_returns_singleton(self, tmp_path):
        log_file = str(tmp_path / "test2.log")
        handler = setup_logging(log_file=log_file)
        assert get_memory_handler() is handler

    def test_setup_logging_clears_existing_handlers(self, tmp_path):
        log_file = str(tmp_path / "test3.log")
        root = logging.getLogger()
        initial_count = len(root.handlers)
        setup_logging(log_file=log_file)
        # Should have exactly 3 handlers: file, console, memory
        assert len(root.handlers) == 3

    def test_memory_handler_emit(self, tmp_path):
        log_file = str(tmp_path / "test4.log")
        handler = setup_logging(log_file=log_file, level="DEBUG")
        logger = logging.getLogger("test_emit")
        logger.info("hello from emit test")
        logs = handler.get_logs(count=10)
        assert any("hello from emit test" in log for log in logs)


class TestMemoryLogHandler:
    def test_basic_logging(self):
        handler = MemoryLogHandler(max_entries=10)
        handler._buffer.append("2024-01-01 [INFO] test: msg1")
        handler._buffer.append("2024-01-01 [ERROR] test: msg2")
        logs = handler.get_logs()
        assert len(logs) == 2

    def test_count_limit(self):
        handler = MemoryLogHandler(max_entries=100)
        for i in range(50):
            handler._buffer.append(f"2024-01-01 [INFO] test: msg{i}")
        logs = handler.get_logs(count=5)
        assert len(logs) == 5
        assert "msg49" in logs[-1]

    def test_level_filter(self):
        handler = MemoryLogHandler(max_entries=10)
        handler._buffer.append("2024-01-01 [INFO] test: info")
        handler._buffer.append("2024-01-01 [ERROR] test: error")
        handler._buffer.append("2024-01-01 [WARNING] test: warn")
        logs = handler.get_logs(level="ERROR")
        assert len(logs) == 1
        assert "error" in logs[0]

    def test_ring_buffer_overflow(self):
        handler = MemoryLogHandler(max_entries=3)
        for i in range(5):
            handler._buffer.append(f"msg{i}")
        logs = handler.get_logs()
        assert len(logs) == 3
        assert logs[0] == "msg2"

    def test_empty_handler(self):
        handler = MemoryLogHandler()
        assert handler.get_logs() == []
