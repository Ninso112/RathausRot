import html
import logging
from typing import List, Optional, Tuple

from rathausrot.utils import chunk_html, strip_html
from rathausrot.scraper import CouncilItem
from rathausrot.llm_client import LLMResult

logger = logging.getLogger(__name__)

VERDICT_EMOJI = {
    "Zustimmung": "✅",
    "Ablehnung": "❌",
    "Enthaltung": "🤔",
}

STAR_RATINGS = {
    1: "★☆☆☆☆",
    2: "★★☆☆☆",
    3: "★★★☆☆",
    4: "★★★★☆",
    5: "★★★★★",
}

DISCLAIMER = (
    "<em>Hinweis: Diese Einschätzungen sind automatisch generierte Prognosen "
    "und stellen keine offiziellen Positionen der Partei dar.</em>"
)


class MatrixFormatter:
    def format_single_item_report(
        self,
        item: CouncilItem,
        result: Optional[LLMResult],
        source_url: str = "",
    ) -> List[str]:
        if source_url:
            source_link = f' – <a href="{html.escape(source_url, quote=True)}">Ratsinfo</a>'
        else:
            source_link = ""
        header = f"<p>🔴 <strong>Neue Vorlage</strong>{source_link}</p>\n<hr>\n"
        body = self.format_item(item, result)
        footer = self.format_footer()
        full_html = header + body + "\n<hr>\n" + footer
        return chunk_html(full_html)

    def format_header(self, kw: int, year: int, source_url: str = "") -> str:
        if source_url:
            source_link = f' – <a href="{html.escape(source_url, quote=True)}">Ratsinfo</a>'
        else:
            source_link = ""
        return (
            f"<h3>🔴 RathausRot – Wochenbericht KW {kw}/{year}{source_link}</h3>\n"
            f"<p>Neue Tagesordnungspunkte und Vorlagen aus dem Stadtrat:</p>\n"
            f"<hr>\n"
        )

    def format_item(self, item: CouncilItem, result: Optional[LLMResult]) -> str:
        safe_url = html.escape(item.url, quote=True)
        safe_title = html.escape(item.title)
        title_link = f'<a href="{safe_url}">{safe_title}</a>'
        parts = [f"<h3>{title_link}</h3>"]
        if item.date:
            parts.append(f"<p><em>Datum: {html.escape(item.date)}</em></p>")
        if result:
            parts.append(f"<p>{html.escape(result.summary)}</p>")
            if result.key_points:
                kp_items = ""
                for kp in result.key_points:
                    if isinstance(kp, dict):
                        text = html.escape(kp.get("text", ""))
                        reason = kp.get("reason", "")
                        if reason:
                            kp_items += f"<li><strong>{text}</strong><br><em>Grund: {html.escape(reason)}</em></li>"
                        else:
                            kp_items += f"<li>{text}</li>"
                    else:
                        kp_items += f"<li>{html.escape(str(kp))}</li>"
                parts.append(f"<ul>{kp_items}</ul>")
            emoji = VERDICT_EMOJI.get(result.verdict, "🤔")
            stars = STAR_RATINGS.get(max(1, min(5, result.relevance_score)), "★★★☆☆")
            parts.append(
                f"<p><strong>Einschätzung:</strong> {emoji} {html.escape(result.verdict)}<br>"
                f"<em>{html.escape(result.verdict_reason)}</em></p>"
            )
            parts.append(f"<p><strong>Relevanz:</strong> {stars}</p>")
        else:
            parts.append(f"<p><em>Keine KI-Analyse verfügbar.</em></p>")
        return "\n".join(parts)

    def format_footer(self) -> str:
        return f"<p>{DISCLAIMER}</p>"

    def format_test_message(self) -> str:
        return (
            "<p><strong>🔴 RathausRot Testmeldung</strong></p>"
            "<p>Der Bot ist korrekt konfiguriert und einsatzbereit.</p>"
            f"<p>{DISCLAIMER}</p>"
        )
