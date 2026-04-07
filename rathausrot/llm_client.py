import json
import logging
import re
import time
from dataclasses import dataclass, field

import requests

from rathausrot.utils import truncate_text
from rathausrot.models import CouncilItem

logger = logging.getLogger(__name__)


class InsufficientCreditsError(Exception):
    """Raised when OpenRouter returns HTTP 402 (no credits remaining)."""


SYSTEM_PROMPT_DISCLAIMER = (
    "Hinweis: Diese Einschätzungen sind automatisch generierte Prognosen und stellen "
    "keine offiziellen Positionen der Partei dar."
)

JSON_SCHEMA_EXAMPLE = """{
  "summary": "Kurze Zusammenfassung des Tagesordnungspunkts",
  "key_points": [
    {"text": "Punkt 1", "reason": "Warum Die Linke so reagieren würde"},
    {"text": "Punkt 2", "reason": "Warum Die Linke so reagieren würde"}
  ],
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
        self.model = config.get("openrouter", {}).get(
            "model", "anthropic/claude-sonnet-4"
        )
        self.max_tokens = config.get("openrouter", {}).get("max_tokens", 1024)
        self.party = config.get("bot", {}).get("party", "")
        self.custom_system_prompt = config.get("openrouter", {}).get(
            "system_prompt", ""
        )

    def analyze_item(self, item: CouncilItem) -> LLMResult | None:
        try:
            system_prompt, user_prompt = self._build_prompt(item)
            raw, tokens = self._complete(system_prompt, user_prompt)
            if not raw:
                return None
            result = self._parse_response(raw)
            result.tokens_used = tokens
            return result
        except InsufficientCreditsError:
            raise
        except (
            requests.exceptions.RequestException,
            json.JSONDecodeError,
            KeyError,
            ValueError,
        ) as exc:
            logger.error("analyze_item failed for %s: %s", item.id, exc)
            return None
        except Exception as exc:
            logger.error(
                "analyze_item unexpected error for %s: %s", item.id, exc, exc_info=True
            )
            return None

    def _build_prompt(self, item: CouncilItem) -> tuple[str, str]:
        if self.custom_system_prompt:
            system = self.custom_system_prompt
        else:
            system = (
                f"Du bist ein Assistent für kommunalpolitische Analyse, der die Fraktion {self.party} "
                f"bei der Vorbereitung von Ratssitzungen unterstützt. "
                f"Antworte ausschließlich mit validem JSON gemäß dem angegebenen Schema.\n\n"
                f"Für jeden Eintrag in key_points liefere ein Objekt mit 'text' (der Kernaussage) "
                f"und 'reason' (eine Begründung, warum {self.party} aus ihrer politischen Perspektive "
                f"so auf diesen Punkt reagieren würde).\n\n"
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

    def _complete(self, system: str, user: str) -> str | None:
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
        delays = [5, 15, 45]
        max_total_seconds = 180
        max_retry_after = 60
        deadline = time.monotonic() + max_total_seconds
        for attempt, delay in enumerate(delays, 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.error("LLM request aborted: overall timeout of %ds exceeded", max_total_seconds)
                break
            try:
                resp = requests.post(
                    self.API_URL, headers=headers, json=payload, timeout=min(60, remaining)
                )
                if resp.status_code == 402:
                    logger.error("OpenRouter credits exhausted (HTTP 402)")
                    raise InsufficientCreditsError(
                        "OpenRouter-Guthaben aufgebraucht (HTTP 402). Bitte Credits aufladen."
                    )
                if resp.status_code in (429, 503):
                    retry_after = min(
                        int(resp.headers.get("Retry-After", delay)),
                        max_retry_after,
                    )
                    logger.warning(
                        "LLM rate limited (HTTP %d), waiting %ds (attempt %d)",
                        resp.status_code,
                        retry_after,
                        attempt,
                    )
                    if attempt < len(delays):
                        sleep_time = min(retry_after, deadline - time.monotonic())
                        if sleep_time > 0:
                            time.sleep(sleep_time)
                    continue
                resp.raise_for_status()
                data = resp.json()
                tokens = data.get("usage", {}).get("total_tokens", 0)
                logger.info("LLM tokens used: %d (attempt %d)", tokens, attempt)
                try:
                    content = data["choices"][0]["message"]["content"]
                except (KeyError, IndexError, TypeError) as exc:
                    logger.warning("Unexpected LLM response structure: %s", exc)
                    break  # Non-transient – retrying won't help
                return content, tokens
            except (requests.exceptions.RequestException, TimeoutError) as exc:
                logger.warning("LLM request attempt %d failed: %s", attempt, exc)
                if attempt < len(delays):
                    sleep_time = min(delay, deadline - time.monotonic())
                    if sleep_time > 0:
                        time.sleep(sleep_time)
        logger.error("All LLM request attempts exhausted for prompt, returning None")
        return None, 0

    def _parse_response(self, text: str) -> LLMResult:
        max_response_chars = 50_000
        if len(text) > max_response_chars:
            logger.warning(
                "LLM response unexpectedly large (%d chars), truncating to %d",
                len(text),
                max_response_chars,
            )
            text = text[:max_response_chars]
        # Try direct JSON parse
        try:
            data = json.loads(text.strip())
            return self._dict_to_result(data)
        except json.JSONDecodeError:
            pass
        # Try ```json ... ``` code block
        code_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if code_match:
            try:
                return self._dict_to_result(json.loads(code_match.group(1)))
            except json.JSONDecodeError:
                pass
        # Fallback: balanced brace extraction
        start = text.find("{")
        if start != -1:
            depth = 0
            for i, ch in enumerate(text[start:], start):
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                if depth == 0:
                    try:
                        return self._dict_to_result(json.loads(text[start : i + 1]))
                    except json.JSONDecodeError:
                        break
        logger.warning("Could not parse LLM response as JSON, using defaults")
        return LLMResult(summary=truncate_text(text, 500))

    def _dict_to_result(self, data: dict) -> LLMResult:
        try:
            score = int(data.get("relevance_score", 3))
        except (ValueError, TypeError):
            score = 3
        raw_kps = data.get("key_points", [])
        key_points = []
        for kp in raw_kps:
            if isinstance(kp, str):
                key_points.append({"text": kp, "reason": ""})
            elif isinstance(kp, dict):
                key_points.append(kp)
        return LLMResult(
            summary=data.get("summary", ""),
            key_points=key_points,
            verdict=data.get("verdict", "Enthaltung"),
            verdict_reason=data.get("verdict_reason", ""),
            relevance_score=max(1, min(5, score)),
        )

    def get_credits(self) -> dict | None:
        """Fetch current OpenRouter credit balance."""
        try:
            resp = requests.get(
                "https://openrouter.ai/api/v1/credits",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
            total = data.get("total_credits", 0.0)
            usage = data.get("total_usage", 0.0)
            return {
                "total_credits": total,
                "total_usage": usage,
                "balance": total - usage,
            }
        except requests.exceptions.RequestException as exc:
            logger.warning("Failed to fetch OpenRouter credits: %s", exc)
            return None
