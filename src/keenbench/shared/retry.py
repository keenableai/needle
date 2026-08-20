import asyncio
from collections.abc import Awaitable, Callable

import httpx

MAX_ERROR_CHARS = 500
RETRY_ATTEMPTS = 3
RETRY_BASE_S = 1.0
RETRY_MAX_S = 30.0
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
    for attempt in range(attempts):
        if attempt:
            await asyncio.sleep(delay)
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
            retry_after = resp.headers.get("retry-after")
            if retry_after is not None:
                try:
                    delay = min(max(float(retry_after), 0.0), RETRY_MAX_S)
                except ValueError:
                    pass
            continue
        return resp, None
    return None, err
