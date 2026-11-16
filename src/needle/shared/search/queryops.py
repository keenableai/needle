from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

EPOCH = date(1970, 1, 1)


def _normalize_host(value: str) -> str:
    host = value.lower()
    if "://" in host:
        host = host.split("://", 1)[1]
    host = host.split("/", 1)[0].split("?", 1)[0].strip(".")
    return host if "." in host else ""


@dataclass(frozen=True)
class QueryOps:
    text: str
    sites: tuple[str, ...]
    after: date | None
    before: date | None

    def text_with_sites(self) -> str:
        return " ".join([self.text, *(f"site:{s}" for s in self.sites)]).strip()


def freshness_window(ops: QueryOps) -> str | None:
    if not (ops.after or ops.before):
        return None
    lo = ops.after or EPOCH
    hi = ops.before or datetime.now(UTC).date()
    return f"{lo.isoformat()}to{hi.isoformat()}"


def recency(ops: QueryOps, now: datetime | None = None) -> str | None:
    if ops.before or not ops.after:
        return None
    current = now or datetime.now(UTC)
    start = datetime(ops.after.year, ops.after.month, ops.after.day, tzinfo=UTC)
    if start > current:
        return None
    elapsed = current - start
    if elapsed <= timedelta(hours=24):
        return "last_24_hours"
    if elapsed <= timedelta(days=7):
        return "last_week"
    if elapsed <= timedelta(days=31):
        return "last_month"
    if elapsed <= timedelta(days=366):
        return "last_year"
    return None


def clipped_text(text: str, max_chars: int) -> str:
    return text[:max_chars].rsplit(" ", 1)[0] if len(text) > max_chars else text


def parse_ops(query: str) -> QueryOps:
    text_parts: list[str] = []
    sites: list[str] = []
    after: date | None = None
    before: date | None = None
    for word in query.split():
        field, sep, value = word.partition(":")
        key = field.lower()
        if sep and value:
            if key == "site":
                host = _normalize_host(value)
                if host:
                    if host not in sites:
                        sites.append(host)
                    continue
            elif key in ("after", "before"):
                try:
                    parsed = date.fromisoformat(value)
                except ValueError:
                    parsed = None
                if parsed is not None:
                    if key == "after":
                        after = parsed
                    else:
                        before = parsed
                    continue
        text_parts.append(word)
    return QueryOps(text=" ".join(text_parts), sites=tuple(sites), after=after, before=before)
