import json
from urllib import request

from app.config import settings
from app.services.rate_limiter import check_rate_limit


def should_search_web(query: str) -> bool:
    lowered = query.strip().lower()
    if lowered in {"hi", "hello", "hey", "thanks", "thank you"}:
        return False
    current_terms = {
        "today",
        "latest",
        "recent",
        "current",
        "news",
        "price",
        "trend",
        "market",
        "web",
        "internet",
        "online",
        "search",
        "look up",
        "who is",
        "what is happening",
        "compare",
    }
    return any(term in lowered for term in current_terms)


def serper_search(query: str, limit: int = 5) -> list[dict]:
    if not settings.SERPER_API_KEY:
        return []
    check_rate_limit("serper_search", max_calls=8, window_seconds=60)

    payload = json.dumps({"q": query, "num": limit}).encode("utf-8")
    http_request = request.Request(
        "https://google.serper.dev/search",
        data=payload,
        headers={
            "X-API-KEY": settings.SERPER_API_KEY,
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with request.urlopen(http_request, timeout=12) as response:
        data = json.loads(response.read().decode("utf-8"))

    results = []
    for item in data.get("organic", [])[:limit]:
        results.append(
            {
                "title": item.get("title"),
                "link": item.get("link"),
                "snippet": item.get("snippet"),
                "date": item.get("date"),
            }
        )
    return results
