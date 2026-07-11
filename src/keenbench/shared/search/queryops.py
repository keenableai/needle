from dataclasses import dataclass
from datetime import date

EPOCH = date(1970, 1, 1)


def _normalize_host(value: str) -> str:
    host = value.lower()
    if "://" in host:
        host = host.split("://", 1)[1]
    host = host.split("/", 1)[0].split("?", 1)[0].strip(".")
    return host if "." in host else ""


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


@dataclass(frozen=True)
class QueryOps:
    text: str
    sites: tuple[str, ...]
    after: date | None
    before: date | None

    def text_with_sites(self) -> str:
        return " ".join([self.text, *(f"site:{s}" for s in self.sites)]).strip()

    def after_ymd(self) -> str | None:
        return self.after.isoformat() if self.after else None

    def before_ymd(self) -> str | None:
        return self.before.isoformat() if self.before else None

    def after_iso8601_start(self) -> str | None:
        return f"{self.after.isoformat()}T00:00:00.000Z" if self.after else None

    def before_iso8601_end(self) -> str | None:
        return f"{self.before.isoformat()}T23:59:59.999Z" if self.before else None

    def after_mdy(self) -> str | None:
        return self.after.strftime("%m/%d/%Y") if self.after else None

    def before_mdy(self) -> str | None:
        return self.before.strftime("%m/%d/%Y") if self.before else None

    def brave_freshness(self, today: date) -> str | None:
        if self.after is None and self.before is None:
            return None
        lo = self.after or EPOCH
        hi = self.before or today
        return f"{lo.isoformat()}to{hi.isoformat()}"


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
                parsed = _parse_date(value)
                if parsed is not None:
                    if key == "after":
                        after = parsed
                    else:
                        before = parsed
                    continue
        text_parts.append(word)
    return QueryOps(text=" ".join(text_parts), sites=tuple(sites), after=after, before=before)
