"""Shared Jinja2 template engine — importable without circular deps."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from jinja2_fragments.fastapi import Jinja2Blocks

TEMPLATES_DIR = Path(__file__).parent / "templates"

templates = Jinja2Blocks(directory=str(TEMPLATES_DIR))


def relative_time(moment: datetime, now: datetime | None = None) -> str:
    """Describe an aware datetime relative to now, e.g. "in 6 days" or "2 hours ago".

    Counts are rounded down, so a public link's remaining life is never overstated.
    Future spans of a day or more also name the leftover hours ("in 6 days 23 hours").
    """
    seconds = (moment - (now or datetime.now(UTC))).total_seconds()
    span = abs(seconds)
    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if span >= size:
            count = int(span // size)
            break
    else:
        return "just now"

    def plural(n: int, word: str) -> str:
        return f"{n} {word}{'' if n == 1 else 's'}"

    label = plural(count, unit)
    if seconds < 0:
        return f"{label} ago"
    hours = int(span % 86400 // 3600)
    if unit == "day" and hours:
        label += " " + plural(hours, "hour")
    return f"in {label}"


def expiry_label(days: int) -> str:
    """When a link created now with this lifetime would expire, in the table's format."""
    return (datetime.now(UTC) + timedelta(days=days)).strftime("%b %d, %Y %H:%M UTC")


templates.env.filters["relative_time"] = relative_time
templates.env.globals["expiry_label"] = expiry_label
