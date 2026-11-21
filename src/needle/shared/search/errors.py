import re

ACCOUNT_STATUSES = frozenset({401, 402, 403, 429, 432, 433})
ACCOUNT_MESSAGE = re.compile(
    r"credit[ _]balance|not enough credits|insufficient[ _]credits|usage limit"
    r"|\bquota\b|insufficient_quota|billing|api[ _-]?key",
    re.IGNORECASE,
)
HTTP_STATUS = re.compile(r"(\d{3}):")


def account_side(error: dict[str, str]) -> bool:
    kind, message = error.get("error_type"), error.get("error_message") or ""
    if kind not in ("http_error", "api_error"):
        return False
    status = HTTP_STATUS.match(message) if kind == "http_error" else None
    code = int(status.group(1)) if status else None
    return code in ACCOUNT_STATUSES or (
        code in (None, 400) and bool(ACCOUNT_MESSAGE.search(message))
    )


def representative_error(errors: list[dict[str, str]]) -> dict[str, str]:
    return next((e for e in errors if not account_side(e)), errors[0])
