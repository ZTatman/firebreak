import re
from typing import Any


def redact(value: Any, pat: str) -> Any:
    """Preserve JSON shape while removing credential fields and echoed PATs."""
    if isinstance(value, dict):
        return {
            key: "[redacted]"
            if re.search(
                r"token|password|secret|authorization|credential|encrypted|^pat$",
                key,
                re.IGNORECASE,
            )
            else redact(item, pat)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item, pat) for item in value]
    if isinstance(value, str):
        value = value.replace(pat, "[redacted]") if pat else value
        value = re.sub(r"(https?://)[^/\s@]+@", r"\1[redacted]@", value)
        return re.sub(
            r"([?&](?:access_token|token|password|secret)=)[^&#\s]*",
            r"\1[redacted]",
            value,
            flags=re.IGNORECASE,
        )
    return value
