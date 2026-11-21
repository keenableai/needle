import asyncio
import random
from collections.abc import Awaitable, Callable

import httpx

MAX_ERROR_CHARS = 500
RETRY_ATTEMPTS = 3
RATE_LIMIT_ATTEMPTS = 6
RETRY_BASE_S = 1.0
RETRY_MAX_S = 60.0
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})


async def send_with_retry(
    send: Callable[[], Awaitable[httpx.Response]],
    *,
    attempts: int,
    base_s: float,
    retry_timeouts: bool = True,
) -> tuple[httpx.Response | None, tuple[str, str] | None]:
    err: tuple[str, str] | None = None
    delay = base_s
    limit = attempts
    for attempt in range(max(attempts, RATE_LIMIT_ATTEMPTS)):
        if attempt:
            if attempt >= limit:
                break
            await asyncio.sleep(delay * random.uniform(1.0, 1.25))
            delay = min(delay * 2, RETRY_MAX_S)
        try:
            resp = await send()
        except httpx.HTTPError as exc:
            detail = str(exc)[:MAX_ERROR_CHARS]
            message = f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__
            err = ("transport", message)
            if not retry_timeouts and isinstance(exc, httpx.TimeoutException):
                return None, err
            continue
        if resp.status_code in RETRYABLE_STATUSES:
            err = ("http_error", f"{resp.status_code}: {resp.text[:MAX_ERROR_CHARS]}")
            if resp.status_code == 429:
                limit = max(attempts, RATE_LIMIT_ATTEMPTS)
            retry_after = resp.headers.get("retry-after")
            if retry_after is not None:
                try:
                    delay = min(max(float(retry_after), 0.0), RETRY_MAX_S)
                except ValueError:
                    pass
            continue
        return resp, None
    return None, err
