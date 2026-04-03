import json
import socket
import threading
import time
from http.client import HTTPConnection
from unittest.mock import MagicMock, patch

import pytest

from rathausrot.healthcheck import HealthCheckHandler, start_healthcheck


def _wait_for_server(port, timeout=5.0):
    """Wait until the server accepts connections."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=1)
            s.close()
            return True
        except (ConnectionRefusedError, OSError):
            time.sleep(0.1)
    return False


def _get_free_port():
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class TestStartHealthcheck:
    def test_port_zero_returns_none(self):
        result = start_healthcheck(0)
        assert result is None

    def test_negative_port_returns_none(self):
        result = start_healthcheck(-1)
        assert result is None

    def test_starts_daemon_thread(self):
        port = _get_free_port()
        thread = start_healthcheck(port)
        assert thread is not None
        assert thread.daemon is True
        assert thread.is_alive()

        if not _wait_for_server(port):
            pytest.skip("Cannot bind to network port (sandbox/CI restriction)")

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
        port = _get_free_port()
        start_healthcheck(port)

        if not _wait_for_server(port):
            pytest.skip("Cannot bind to network port (sandbox/CI restriction)")

        conn = HTTPConnection("127.0.0.1", port, timeout=2)
        try:
            conn.request("GET", "/other")
            resp = conn.getresponse()
            assert resp.status == 404
        finally:
            conn.close()

    def test_health_with_last_run_file(self, tmp_path):
        port = _get_free_port()
        fake_file = tmp_path / "last_run.txt"
        fake_file.write_text("2024-06-15T10:00:00")

        with patch("rathausrot.scheduler.LAST_RUN_FILE", fake_file):
            start_healthcheck(port)

            if not _wait_for_server(port):
                pytest.skip("Cannot bind to network port (sandbox/CI restriction)")

            conn = HTTPConnection("127.0.0.1", port, timeout=2)
            try:
                conn.request("GET", "/health")
                resp = conn.getresponse()
                data = json.loads(resp.read())
                assert data["status"] == "ok"
            finally:
                conn.close()
