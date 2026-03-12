import os
import tempfile

import pytest
import yaml

from rathausrot.config_manager import ConfigManager, DEFAULT_CONFIG


class TestDeepMerge:
    def test_merge_overwrites_scalars(self):
        cm = ConfigManager.__new__(ConfigManager)
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        result = cm._deep_merge(base, override)
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_merge_nested_dicts(self):
        cm = ConfigManager.__new__(ConfigManager)
        base = {"outer": {"a": 1, "b": 2}}
        override = {"outer": {"b": 3}}
        result = cm._deep_merge(base, override)
        assert result == {"outer": {"a": 1, "b": 3}}

    def test_merge_preserves_base(self):
        cm = ConfigManager.__new__(ConfigManager)
        base = {"x": {"y": 1}}
        override = {}
        result = cm._deep_merge(base, override)
        assert result == {"x": {"y": 1}}


class TestLoadSave:
    def test_load_nonexistent_returns_defaults(self):
        cm = ConfigManager(config_path="/tmp/nonexistent_rathausrot_test.yaml")
        config = cm.load()
        assert config["matrix"]["homeserver"] == ""
        assert config["bot"]["interval_hours"] == 168

    def test_save_and_load_roundtrip(self):
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            path = f.name
        try:
            cm = ConfigManager(config_path=path)
            test_config = {
                "matrix": {"homeserver": "https://test.com", "username": "@bot:test.com",
                           "access_token": "tok", "room_id": "!room:test.com", "room_ids": []},
                "openrouter": {"api_key": "key", "model": "m", "max_tokens": 512, "system_prompt": ""},
                "scraper": {"ratsinfo_url": "http://rats.de", "max_pdf_pages": 5,
                           "request_timeout": 15, "keywords": []},
                "bot": {"interval_hours": 24, "schedule_day": "monday", "schedule_time": "09:00",
                       "party": "Test", "log_level": "DEBUG", "log_file": "test.log",
                       "allowed_users": [], "relevance_threshold": 1, "healthcheck_port": 0},
            }
            cm.save(test_config)

            cm2 = ConfigManager(config_path=path)
            loaded = cm2.load()
            assert loaded["matrix"]["homeserver"] == "https://test.com"
            assert loaded["bot"]["interval_hours"] == 24
        finally:
            os.unlink(path)

    def test_save_file_permissions(self):
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            path = f.name
        try:
            cm = ConfigManager(config_path=path)
            cm.save(DEFAULT_CONFIG)
            mode = oct(os.stat(path).st_mode)[-3:]
            assert mode == "600"
        finally:
            os.unlink(path)


class TestIsConfigured:
    def test_unconfigured_defaults(self):
        cm = ConfigManager(config_path="/tmp/nonexistent_rathausrot_test2.yaml")
        assert cm.is_configured() is False

    def test_configured_with_all_required(self):
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            yaml.dump({
                "matrix": {"homeserver": "https://m.org", "access_token": "tok",
                           "room_id": "!r:m.org"},
                "openrouter": {"api_key": "sk-test"},
                "scraper": {"ratsinfo_url": "http://rats.de"},
            }, f)
            path = f.name
        try:
            cm = ConfigManager(config_path=path)
            assert cm.is_configured() is True
        finally:
            os.unlink(path)

    def test_missing_homeserver_not_configured(self):
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            yaml.dump({
                "matrix": {"access_token": "tok", "room_id": "!r:m.org"},
                "openrouter": {"api_key": "sk-test"},
                "scraper": {"ratsinfo_url": "http://rats.de"},
            }, f)
            path = f.name
        try:
            cm = ConfigManager(config_path=path)
            assert cm.is_configured() is False
        finally:
            os.unlink(path)

    def test_missing_ratsinfo_url_not_configured(self):
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            yaml.dump({
                "matrix": {"homeserver": "https://m.org", "access_token": "tok",
                           "room_id": "!r:m.org"},
                "openrouter": {"api_key": "sk-test"},
            }, f)
            path = f.name
        try:
            cm = ConfigManager(config_path=path)
            assert cm.is_configured() is False
        finally:
            os.unlink(path)


class TestGet:
    def test_get_nested(self):
        cm = ConfigManager(config_path="/tmp/nonexistent_rathausrot_test3.yaml")
        assert cm.get("bot", "interval_hours") == 168

    def test_get_missing_returns_default(self):
        cm = ConfigManager(config_path="/tmp/nonexistent_rathausrot_test4.yaml")
        assert cm.get("nonexistent", "key", default="fallback") == "fallback"
