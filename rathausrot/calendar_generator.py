import logging
from datetime import datetime, timedelta

from rathausrot.models import CouncilItem
from rathausrot.utils import parse_german_date

logger = logging.getLogger(__name__)


def generate_ics(items: list[CouncilItem]) -> bytes:
    """Generate an ICS calendar file from a list of CouncilItems."""
    try:
        from icalendar import Calendar, Event
    except ImportError as exc:
        raise ImportError(
            "icalendar package required: pip install 'icalendar>=5.0'"
        ) from exc

    cal = Calendar()
    cal.add("prodid", "-//RathausRot//DE")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("x-wr-calname", "RathausRot – Stadtrat")

    for item in items:
        dt = parse_german_date(item.date)
        if dt is None:
            continue  # Skip items without parseable dates

        event = Event()
        event.add("uid", f"{item.id}@rathausrot")
        event.add("summary", item.title)
        if item.url:
            event.add("url", item.url)
        if item.city_name:
            event.add("location", item.city_name)
        # parse_german_date returns a date object; convert to datetime
        # so we can add a timedelta in hours without a TypeError.
        dt_start = datetime.combine(dt, datetime.min.time())
        event.add("dtstart", dt_start)
        event.add("dtend", dt_start + timedelta(hours=1))
        cal.add_component(event)

    return cal.to_ical()
