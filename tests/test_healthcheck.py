import json
import threading
import time
from http.client import HTTPConnection
from unittest.mock import MagicMock, patch

import pytest

from rathausrot.healthcheck import HealthCheckHandler, start_healthcheck


class TestStartHealthcheck:
    def test_port_zero_returns_none(self):
        result = start_healthcheck(0)
        assert result is None

    def test_negative_port_returns_none(self):
        result = start_healthcheck(-1)
        assert result is None

    def test_starts_daemon_thread(self):
        # Use a random high port to avoid conflicts
        import socket
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()

        thread = start_healthcheck(port)
        assert thread is not None
        assert thread.daemon is True
        assert thread.is_alive()
        time.sleep(0.3)  # Let server start

        # Test /health endpoint
        conn = HTTPConnection("127.0.0.1", port, timeout=2)
        try:
            conn.request("GET", "/health")
            resp = conn.getresponse()
            assert resp.status == 200
            data = json.loads(resp.read())
            assert data["status"] == "ok"
            assert "last_run" in data
            assert "scrape_running" in data
        finally:
            conn.close()

    def test_404_for_non_health_path(self):
        import socket
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()

        start_healthcheck(port)
        time.sleep(0.3)

        conn = HTTPConnection("127.0.0.1", port, timeout=2)
        try:
            conn.request("GET", "/other")
            resp = conn.getresponse()
            assert resp.status == 404
        finally:
            conn.close()

    def test_health_with_last_run_file(self, tmp_path):
        import socket
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()

        fake_file = tmp_path / "last_run.txt"
        fake_file.write_text("2024-06-15T10:00:00")

        with patch("rathausrot.healthcheck.Path") as MockPath:
            MockPath.return_value = fake_file
            start_healthcheck(port)
            time.sleep(0.3)

            conn = HTTPConnection("127.0.0.1", port, timeout=2)
            try:
                conn.request("GET", "/health")
                resp = conn.getresponse()
                data = json.loads(resp.read())
                assert data["status"] == "ok"
            finally:
                conn.close()
