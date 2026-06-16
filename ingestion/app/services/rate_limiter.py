from collections import defaultdict, deque
from time import monotonic


class RateLimitError(RuntimeError):
    pass


_calls: dict[str, deque[float]] = defaultdict(deque)


def check_rate_limit(key: str, max_calls: int, window_seconds: int) -> None:
    now = monotonic()
    calls = _calls[key]
    while calls and now - calls[0] > window_seconds:
        calls.popleft()

    if len(calls) >= max_calls:
        raise RateLimitError(
            f"Rate limit exceeded for {key}. Try again in a minute."
        )

    calls.append(now)
