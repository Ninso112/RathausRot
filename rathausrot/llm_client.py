import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional, Tuple

import requests

from rathausrot.utils import truncate_text
from rathausrot.scraper import CouncilItem

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_DISCLAIMER = (
    "Hinweis: Diese Einschätzungen sind automatisch generierte Prognosen und stellen "
    "keine offiziellen Positionen der Partei dar."
)

JSON_SCHEMA_EXAMPLE = """{
  "summary": "Kurze Zusammenfassung des Tagesordnungspunkts",
  "key_points": ["Punkt 1", "Punkt 2", "Punkt 3"],
  "verdict": "Zustimmung|Ablehnung|Enthaltung",
  "verdict_reason": "Begründung der Einschätzung",
  "relevance_score": 3
}"""


@dataclass
class LLMResult:
    summary: str
    key_points: list = field(default_factory=list)
    verdict: str = "Enthaltung"
    verdict_reason: str = ""
    relevance_score: int = 3
    tokens_used: int = 0


class OpenRouterClient:
    API_URL = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(self, config: dict):
        self.api_key = config.get("openrouter", {}).get("api_key", "")
        self.model = config.get("openrouter", {}).get("model", "anthropic/claude-sonnet-4")
        self.max_tokens = config.get("openrouter", {}).get("max_tokens", 1024)
        self.party = config.get("bot", {}).get("party", "")

    def analyze_item(self, item: CouncilItem) -> Optional[LLMResult]:
        try:
            system_prompt, user_prompt = self._build_prompt(item)
            raw = self._complete(system_prompt, user_prompt)
            if not raw:
                return None
            result = self._parse_response(raw)
            return result
        except Exception as exc:
            logger.error("analyze_item failed for %s: %s", item.id, exc)
            return None

    def _build_prompt(self, item: CouncilItem) -> Tuple[str, str]:
        system = (
            f"Du bist ein Assistent für kommunalpolitische Analyse, der die Fraktion {self.party} "
            f"bei der Vorbereitung von Ratssitzungen unterstützt. "
            f"Antworte ausschließlich mit validem JSON gemäß dem angegebenen Schema.\n\n"
            f"{SYSTEM_PROMPT_DISCLAIMER}"
        )
        body = truncate_text(item.body_text, 12000)
        pdf_summary = ""
        if item.pdf_texts:
            combined_pdf = "\n\n".join(item.pdf_texts)
            pdf_summary = f"\n\nAngehängte Dokumente (Auszug):\n{truncate_text(combined_pdf, 3000)}"
        user = (
            f"Analysiere den folgenden Kommunalpolitischen Tagesordnungspunkt und antworte "
            f"ausschließlich mit JSON gemäß diesem Schema:\n{JSON_SCHEMA_EXAMPLE}\n\n"
            f"Tagesordnungspunkt: {item.title}\n"
            f"URL: {item.url}\n"
            f"Datum: {item.date}\n\n"
            f"Beschreibung:\n{body}"
            f"{pdf_summary}\n\n"
            f"Antworte NUR mit dem JSON-Objekt, ohne zusätzlichen Text."
        )
        return system, user

    def _complete(self, system: str, user: str) -> Optional[str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": self.max_tokens,
        }
        delays = [2, 4, 8]
        for attempt, delay in enumerate(delays, 1):
            try:
                resp = requests.post(
                    self.API_URL, headers=headers, json=payload, timeout=60
                )
                resp.raise_for_status()
                data = resp.json()
                tokens = data.get("usage", {}).get("total_tokens", 0)
                logger.info("LLM tokens used: %d (attempt %d)", tokens, attempt)
                content = data["choices"][0]["message"]["content"]
                return content
            except requests.exceptions.RequestException as exc:
                logger.warning("LLM request attempt %d failed: %s", attempt, exc)
                if attempt < len(delays):
                    time.sleep(delay)
        return None

    def _parse_response(self, text: str) -> LLMResult:
        # Try direct JSON parse
        try:
            data = json.loads(text.strip())
            return self._dict_to_result(data)
        except json.JSONDecodeError:
            pass
        # Fallback: extract JSON block with regex
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
                return self._dict_to_result(data)
            except json.JSONDecodeError:
                pass
        logger.warning("Could not parse LLM response as JSON, using defaults")
        return LLMResult(summary=truncate_text(text, 500))

    def _dict_to_result(self, data: dict) -> LLMResult:
        return LLMResult(
            summary=data.get("summary", ""),
            key_points=data.get("key_points", []),
            verdict=data.get("verdict", "Enthaltung"),
            verdict_reason=data.get("verdict_reason", ""),
            relevance_score=int(data.get("relevance_score", 3)),
        )
