import copy
import os
import re
import tempfile
import logging
from contextlib import suppress
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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
        "data_retention_days": 180,
        "failure_alert_threshold": 3,
    },
    "cities": [],
}


def _is_http_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except (ValueError, AttributeError):
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def validate_config(config: dict) -> list[str]:
    """Return a list of human-readable problems found in `config` (empty = valid)."""
    errors: list[str] = []
    matrix = config.get("matrix", {}) or {}
    openrouter = config.get("openrouter", {}) or {}
    scraper = config.get("scraper", {}) or {}
    bot = config.get("bot", {}) or {}

    homeserver = matrix.get("homeserver", "")
    if not homeserver:
        errors.append("matrix.homeserver fehlt.")
    elif not _is_http_url(homeserver):
        errors.append(
            f"matrix.homeserver ist keine gültige http(s)-URL: {homeserver!r}"
        )

    username = matrix.get("username", "")
    if not username:
        errors.append("matrix.username fehlt.")
    elif not re.match(r"^@[^:]+:.+$", username):
        errors.append(
            f"matrix.username muss das Format @name:server haben: {username!r}"
        )

    if not matrix.get("access_token"):
        errors.append("matrix.access_token fehlt (Setup-Wizard ausführen).")

    if not (matrix.get("room_id") or matrix.get("room_ids")):
        errors.append("Kein Matrix-Raum konfiguriert (room_id oder room_ids).")

    if not openrouter.get("api_key"):
        errors.append("openrouter.api_key fehlt.")

    max_tokens = openrouter.get("max_tokens", 1024)
    if not isinstance(max_tokens, int) or max_tokens <= 0:
        errors.append("openrouter.max_tokens muss eine positive Ganzzahl sein.")

    cities = config.get("cities", []) or []
    base_url = scraper.get("ratsinfo_url", "")
    has_any_ratsinfo = bool(base_url) or any(c.get("ratsinfo_url") for c in cities)
    if not has_any_ratsinfo:
        errors.append("scraper.ratsinfo_url fehlt (und keine Stadt hat eine URL).")
    if base_url and not _is_http_url(base_url):
        errors.append(
            f"scraper.ratsinfo_url ist keine gültige http(s)-URL: {base_url!r}"
        )
    for city in cities:
        url = city.get("ratsinfo_url", "")
        if url and not _is_http_url(url):
            name = city.get("name", "?")
            errors.append(
                f"cities[{name}].ratsinfo_url ist keine gültige http(s)-URL: {url!r}"
            )

    threshold = bot.get("relevance_threshold", 1)
    if not isinstance(threshold, int) or not 1 <= threshold <= 5:
        errors.append("bot.relevance_threshold muss zwischen 1 und 5 liegen.")

    interval = bot.get("interval_minutes", 360)
    if not isinstance(interval, int) or interval <= 0:
        errors.append("bot.interval_minutes muss eine positive Ganzzahl sein.")

    port = bot.get("healthcheck_port", 0)
    if not isinstance(port, int) or not 0 <= port <= 65535:
        errors.append("bot.healthcheck_port muss zwischen 0 und 65535 liegen.")

    return errors


def get_cities_from_config(config: dict) -> list[dict]:
    """Return normalized city list from a config dict. Usable without a ConfigManager instance."""
    cities = config.get("cities", [])
    base_scraper = config.get("scraper", {})
    base_matrix = config.get("matrix", {})
    base_openrouter = config.get("openrouter", {})
    if cities:
        result = []
        for c in cities:
            result.append(
                {
                    "name": c.get("name", ""),
                    "ratsinfo_url": c.get("ratsinfo_url")
                    or base_scraper.get("ratsinfo_url", ""),
                    "room_id": c.get("room_id") or base_matrix.get("room_id", ""),
                    "keywords": c.get("keywords", base_scraper.get("keywords", [])),
                    "system_prompt": c.get("system_prompt")
                    or base_openrouter.get("system_prompt", ""),
                }
            )
        return result
    return [
        {
            "name": "",
            "ratsinfo_url": base_scraper.get("ratsinfo_url", ""),
            "room_id": base_matrix.get("room_id", ""),
            "keywords": base_scraper.get("keywords", []),
            "system_prompt": base_openrouter.get("system_prompt", ""),
        }
    ]


class ConfigManager:
    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = Path(config_path)
        self._config: dict | None = None

    def _deep_merge(self, base: dict, override: dict) -> dict:
        result = dict(base)
        for key, value in override.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    def load(self) -> dict:
        if self._config is None:
            if self.config_path.exists():
                with open(self.config_path, encoding="utf-8") as f:
                    user_config = yaml.safe_load(f)
                if not isinstance(user_config, dict):
                    user_config = {}
                self._config = self._deep_merge(
                    copy.deepcopy(DEFAULT_CONFIG), user_config
                )
            else:
                self._config = copy.deepcopy(DEFAULT_CONFIG)
        # Environment variable overrides for secrets (applied on every call)
        env_token = os.environ.get("MATRIX_ACCESS_TOKEN")
        if env_token:
            self._config.setdefault("matrix", {})
            self._config["matrix"]["access_token"] = env_token
        env_api_key = os.environ.get("OPENROUTER_API_KEY")
        if env_api_key:
            self._config.setdefault("openrouter", {})
            self._config["openrouter"]["api_key"] = env_api_key
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
            with suppress(OSError):
                os.unlink(tmp_path)
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
        # Multi-city configs may have per-city ratsinfo_urls without a global one
        cities = config.get("cities", [])
        has_ratsinfo = bool(ratsinfo_url) or any(c.get("ratsinfo_url") for c in cities)
        return bool(token and api_key and homeserver and has_room and has_ratsinfo)

    def get_cities(self) -> list[dict]:
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
