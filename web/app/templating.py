"""Shared Jinja2 template engine — importable without circular deps."""

from datetime import UTC, datetime
from pathlib import Path

from jinja2_fragments.fastapi import Jinja2Blocks

TEMPLATES_DIR = Path(__file__).parent / "templates"

templates = Jinja2Blocks(directory=str(TEMPLATES_DIR))


def relative_time(moment: datetime, now: datetime | None = None) -> str:
    """Describe an aware datetime relative to now, e.g. "in 6 days" or "2 hours ago"."""
    seconds = (moment - (now or datetime.now(UTC))).total_seconds()
    span = abs(seconds)
    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if span >= size:
            count = round(span / size)
            break
    else:
        return "just now"
    label = f"{count} {unit}{'' if count == 1 else 's'}"
    return f"in {label}" if seconds > 0 else f"{label} ago"


templates.env.filters["relative_time"] = relative_time
