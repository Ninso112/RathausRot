import os
import tempfile
import logging
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "matrix": {
        "homeserver": "",
        "username": "",
        "access_token": "",
        "room_id": "",
        "room_ids": [],
    },
    "openrouter": {
        "api_key": "",
        "model": "anthropic/claude-sonnet-4",
        "max_tokens": 1024,
    },
    "scraper": {
        "ratsinfo_url": "",
        "max_pdf_pages": 10,
        "request_timeout": 30,
    },
    "bot": {
        "interval_hours": 168,
        "schedule_day": "monday",
        "schedule_time": "08:00",
        "party": "",
        "log_level": "INFO",
        "log_file": "rathausrot.log",
        "allowed_users": [],
    },
}


class ConfigManager:
    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = Path(config_path)
        self._config: Optional[dict] = None

    def _deep_merge(self, base: dict, override: dict) -> dict:
        result = dict(base)
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    def load(self) -> dict:
        if self._config is not None:
            return self._config
        if self.config_path.exists():
            with open(self.config_path, "r", encoding="utf-8") as f:
                user_config = yaml.safe_load(f) or {}
            self._config = self._deep_merge(DEFAULT_CONFIG, user_config)
        else:
            self._config = dict(DEFAULT_CONFIG)
        return self._config

    def save(self, config: dict) -> None:
        dir_path = self.config_path.parent
        fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
        try:
            os.close(fd)
            os.chmod(tmp_path, 0o600)
            with open(tmp_path, "w", encoding="utf-8") as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
            os.replace(tmp_path, self.config_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        self._config = config
        logger.info("Configuration saved to %s", self.config_path)

    def is_configured(self) -> bool:
        config = self.load()
        token = config.get("matrix", {}).get("access_token", "")
        api_key = config.get("openrouter", {}).get("api_key", "")
        return bool(token and api_key)

    def get(self, *keys: str, default: Any = None) -> Any:
        config = self.load()
        value = config
        for key in keys:
            if not isinstance(value, dict):
                return default
            value = value.get(key)
            if value is None:
                return default
        return value
