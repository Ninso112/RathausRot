import os
import tempfile
import logging
from pathlib import Path
from typing import Any, List, Optional

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
        "system_prompt": "",
    },
    "scraper": {
        "ratsinfo_url": "",
        "max_pdf_pages": 10,
        "request_timeout": 30,
        "keywords": [],
    },
    "bot": {
        "interval_minutes": 360,
        "party": "Die Linke",
        "log_level": "INFO",
        "log_file": "rathausrot.log",
        "allowed_users": [],
        "relevance_threshold": 1,
        "healthcheck_port": 0,
        "send_pdf_attachments": False,
    },
    "cities": [],
}


def get_cities_from_config(config: dict) -> List[dict]:
    """Return normalized city list from a config dict. Usable without a ConfigManager instance."""
    cities = config.get("cities", [])
    base_scraper = config.get("scraper", {})
    base_matrix = config.get("matrix", {})
    base_openrouter = config.get("openrouter", {})
    if cities:
        result = []
        for c in cities:
            result.append({
                "name": c.get("name", ""),
                "ratsinfo_url": c.get("ratsinfo_url") or base_scraper.get("ratsinfo_url", ""),
                "room_id": c.get("room_id") or base_matrix.get("room_id", ""),
                "keywords": c.get("keywords", base_scraper.get("keywords", [])),
                "system_prompt": c.get("system_prompt") or base_openrouter.get("system_prompt", ""),
            })
        return result
    return [{
        "name": "",
        "ratsinfo_url": base_scraper.get("ratsinfo_url", ""),
        "room_id": base_matrix.get("room_id", ""),
        "keywords": base_scraper.get("keywords", []),
        "system_prompt": base_openrouter.get("system_prompt", ""),
    }]


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
        matrix = config.get("matrix", {})
        token = matrix.get("access_token", "")
        homeserver = matrix.get("homeserver", "")
        room_id = matrix.get("room_id", "")
        room_ids = matrix.get("room_ids", [])
        api_key = config.get("openrouter", {}).get("api_key", "")
        ratsinfo_url = config.get("scraper", {}).get("ratsinfo_url", "")
        has_room = bool(room_id or room_ids)
        return bool(token and api_key and homeserver and has_room and ratsinfo_url)

    def get_cities(self) -> List[dict]:
        """Return normalized city list. Falls back to global config if cities: [] is absent."""
        return get_cities_from_config(self.load())

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
