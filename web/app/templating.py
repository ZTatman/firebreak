"""Shared Jinja2 template engine — importable without circular deps."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from jinja2_fragments.fastapi import Jinja2Blocks

from app.models.grant import LINK_LIFETIME_DAYS, group_by_status

TEMPLATES_DIR = Path(__file__).parent / "templates"

templates = Jinja2Blocks(directory=str(TEMPLATES_DIR))


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def relative_time(moment: datetime, now: datetime | None = None) -> str:
    """Describe an aware datetime relative to now, e.g. "in 6 days" or "2 hours ago".

    Counts are rounded down, so a public link's remaining life is never overstated.
    Future spans of a day or more also name the leftover hours ("in 6 days 23 hours").
    """
    seconds = (moment - (now or datetime.now(UTC))).total_seconds()
    days, rest = divmod(int(abs(seconds)), 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        label = _plural(days, "day")
        if seconds > 0 and hours:
            label += " " + _plural(hours, "hour")
    elif hours:
        label = _plural(hours, "hour")
    elif minutes:
        label = _plural(minutes, "minute")
    else:
        return "just now"
    return f"in {label}" if seconds > 0 else f"{label} ago"


def utc_datetime(moment: datetime) -> str:
    """Format an instant for display, e.g. "Nov 30, 2026 23:59 UTC"."""
    return moment.astimezone(UTC).strftime("%b %d, %Y %H:%M UTC")


def utc_date(moment: datetime) -> str:
    """Format an instant's UTC date, e.g. "Nov 30, 2026"."""
    return moment.astimezone(UTC).strftime("%b %d, %Y")


def expiry_label(days: int) -> str:
    """When a link created now with this lifetime would expire."""
    return utc_datetime(datetime.now(UTC) + timedelta(days=days))


templates.env.filters.update(
    by_status=group_by_status,
    relative_time=relative_time,
    utc_datetime=utc_datetime,
    utc_date=utc_date,
)
templates.env.globals.update(
    expiry_label=expiry_label, lifetime_days=LINK_LIFETIME_DAYS
)
