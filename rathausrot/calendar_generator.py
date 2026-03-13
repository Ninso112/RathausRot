import re
import logging
from datetime import date, datetime
from typing import List, Optional

from rathausrot.scraper import CouncilItem

logger = logging.getLogger(__name__)


def generate_ics(items: List[CouncilItem]) -> bytes:
    """Generate an ICS calendar file from a list of CouncilItems."""
    try:
        from icalendar import Calendar, Event
    except ImportError:
        raise ImportError("icalendar package required: pip install 'icalendar>=5.0'")

    cal = Calendar()
    cal.add("prodid", "-//RathausRot//DE")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("x-wr-calname", "RathausRot – Stadtrat")

    for item in items:
        event = Event()
        event.add("uid", f"{item.id}@rathausrot")
        event.add("summary", item.title)
        if item.url:
            event.add("url", item.url)
        if item.city_name:
            event.add("location", item.city_name)

        dt = _parse_item_date(item.date)
        if dt is not None:
            event.add("dtstart", dt)
            event.add("dtend", dt)
        else:
            today = date.today()
            event.add("dtstart", today)
            event.add("dtend", today)

        cal.add_component(event)

    return cal.to_ical()


def _parse_item_date(date_str: str) -> Optional[date]:
    if not date_str:
        return None
    cleaned = re.sub(r'^[A-Za-z\u00c0-\u024f]+,\s*', '', date_str.strip())
    for fmt in ("%d.%m.%Y %H:%M Uhr", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None
