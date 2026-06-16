from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import settings


def runtime_context() -> dict:
    timezone = settings.DEFAULT_TIMEZONE
    try:
        now = datetime.now(ZoneInfo(timezone))
    except Exception:
        timezone = "UTC"
        now = datetime.utcnow()

    return {
        "current_datetime": now.isoformat(),
        "current_date": now.date().isoformat(),
        "timezone": timezone,
        "default_region": settings.DEFAULT_REGION,
    }


def runtime_context_text() -> str:
    context = runtime_context()
    return "\n".join(
        [
            "Runtime context:",
            f"- Current date: {context['current_date']}",
            f"- Current datetime: {context['current_datetime']}",
            f"- Timezone: {context['timezone']}",
            f"- Default region: {context['default_region']}",
            "- Unless the user specifies another location, interpret regional questions with this default region.",
        ]
    )
