import re
import string
import unicodedata
from typing import Any

LEGAL_SUFFIXES = frozenset(
    "incorporated inc corporation corp company co limited ltd llc plc gmbh ag sa nv se spa"
    " kk pte pty bv oyj ab as lp holding holdings group the".split()
)

_RAW_COUNTRY_ALIASES = {
    "us": "united states",
    "usa": "united states",
    "u.s.": "united states",
    "u.s.a.": "united states",
    "united states of america": "united states",
    "america": "united states",
    "uk": "united kingdom",
    "u.k.": "united kingdom",
    "great britain": "united kingdom",
    "britain": "united kingdom",
    "uae": "united arab emirates",
    "prc": "china",
    "people's republic of china": "china",
    "republic of korea": "south korea",
    "korea": "south korea",
    "russian federation": "russia",
    "deutschland": "germany",
    "nederland": "netherlands",
    "holland": "netherlands",
}

_PUNCT = set(string.punctuation)
_ARTICLES = re.compile(r"\b(a|an|the)\b")
_YEAR_RE = re.compile(r"\b(1[5-9]\d{2}|20\d{2})\b")
_AMOUNT_RE = re.compile(
    r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"[ \t]*(trillion|billion|million|thousand|tn|bn|mn|mm|[tbmk])?\b",
    re.IGNORECASE,
)
_SCALE = {
    "trillion": 1e12,
    "tn": 1e12,
    "t": 1e12,
    "billion": 1e9,
    "bn": 1e9,
    "b": 1e9,
    "million": 1e6,
    "mn": 1e6,
    "mm": 1e6,
    "m": 1e6,
    "thousand": 1e3,
    "k": 1e3,
}


def squad_norm(value: Any) -> str:
    s = unicodedata.normalize("NFKC", str(value if value is not None else "")).lower()
    s = "".join(" " if ch in _PUNCT else ch for ch in s)
    s = _ARTICLES.sub(" ", s)
    return " ".join(s.split())


COUNTRY_ALIASES = {squad_norm(k): v for k, v in _RAW_COUNTRY_ALIASES.items()}


def strip_legal(value: Any) -> str:
    return " ".join(t for t in squad_norm(value).split() if t not in LEGAL_SUFFIXES)


def registrable_domain(value: Any) -> str:
    s = unicodedata.normalize("NFKC", str(value if value is not None else "")).strip().lower()
    s = re.sub(r"^[a-z][a-z0-9+.\-]*://", "", s)
    s = s.split("/")[0].split("?")[0].split(":")[0]
    s = re.sub(r"^www\.", "", s)
    parts = [p for p in s.split(".") if p]
    return ".".join(parts[-2:]) if len(parts) >= 2 else s


def phrase_in(phrase: str, text_norm: str) -> bool:
    return bool(phrase) and f" {phrase} " in f" {text_norm} "


def text_years(raw_text: str) -> set[int]:
    return {int(m) for m in _YEAR_RE.findall(raw_text)}


def text_amounts(raw_text: str) -> list[float]:
    out = []
    for num, suffix in _AMOUNT_RE.findall(raw_text):
        out.append(float(num.replace(",", "")) * _SCALE.get(suffix.lower(), 1.0))
    return out


def parse_amount(value: Any) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    amounts = text_amounts(str(value or ""))
    return amounts[0] if amounts else None


def _forms(value: Any, aliases: tuple[str, ...]) -> list[Any]:
    return [f for f in [value, *aliases] if f not in (None, "")]


def _short_in(form_raw: str, raw_text: str) -> bool:
    pat = rf"(?<![A-Za-z0-9]){re.escape(form_raw)}(?![A-Za-z0-9])"
    return re.search(pat, raw_text) is not None


def _match_person(value: Any, aliases: tuple[str, ...], text_norm: str) -> bool:
    text_tokens = text_norm.split()
    for form in _forms(value, aliases):
        f = squad_norm(form)
        if phrase_in(f, text_norm):
            return True
        tokens = f.split()
        if len(tokens) < 2:
            continue
        first, last = tokens[0], tokens[-1]
        if len(first) < 3:
            continue
        for i, t in enumerate(text_tokens):
            if t != last:
                continue
            for w in text_tokens[max(0, i - 3) : i]:
                if len(w) >= 3 and (w.startswith(first) or first.startswith(w)):
                    return True
    return False


def _item_in(item_norm: str, text_norm: str) -> bool:
    if phrase_in(item_norm, text_norm):
        return True
    if " " not in item_norm and len(item_norm) > 3:
        alt = item_norm[:-1] if item_norm.endswith("s") else item_norm + "s"
        return phrase_in(alt, text_norm)
    return False


def _match_entity(value: Any, aliases: tuple[str, ...], text_norm: str) -> bool:
    stripped_text = " ".join(t for t in text_norm.split() if t not in LEGAL_SUFFIXES)
    return any(_item_in(strip_legal(f), stripped_text) for f in _forms(value, aliases))


def _match_list(value: Any, aliases: tuple[str, ...], text_norm: str) -> bool:
    items = list(value) if isinstance(value, list | tuple | set) else [value]
    return _match_entity(None, tuple(str(i) for i in items) + aliases, text_norm)


def _match_year(value: Any, aliases: tuple[str, ...], raw_text: str) -> bool:
    golds = set()
    for f in _forms(value, aliases):
        try:
            golds.add(int(f))
        except (TypeError, ValueError):
            continue
    return bool(golds & text_years(raw_text))


def _match_country(value: Any, aliases: tuple[str, ...], text_norm: str, raw_text: str) -> bool:
    gold_norm = squad_norm(value)
    canonical = COUNTRY_ALIASES.get(gold_norm, gold_norm)
    long_forms = {canonical, gold_norm}
    short_forms = set()
    for a in aliases:
        norm = squad_norm(a)
        if len(norm.replace(" ", "")) <= 3:
            short_forms.add(str(a).strip())
        elif norm:
            long_forms.add(norm)
    for surface, canon in COUNTRY_ALIASES.items():
        if canon != canonical:
            continue
        if len(surface.replace(" ", "")) <= 3:
            short_forms.add("".join(surface.split()).upper())
        else:
            long_forms.add(surface)
    if any(phrase_in(f, text_norm) for f in long_forms):
        return True
    return any(_short_in(f, raw_text) for f in short_forms if f)


def _match_domain(value: Any, aliases: tuple[str, ...], raw_text: str, url: str) -> bool:
    for form in _forms(value, aliases):
        dom = registrable_domain(form)
        if not dom or "." not in dom:
            continue
        if registrable_domain(url) == dom or dom in raw_text.lower():
            return True
    return False


def _match_exact_id(value: Any, aliases: tuple[str, ...], raw_text: str) -> bool:
    for form in _forms(value, aliases):
        norm = re.sub(r"[\s.]", "", str(form)).upper()
        if len(norm) < 2:
            continue
        if len(norm) <= 6:
            if _short_in(norm, raw_text):
                return True
        elif norm in re.sub(r"[^A-Z0-9]", "", raw_text.upper()):
            return True
    return False


def _match_amount(value: Any, aliases: tuple[str, ...], raw_text: str, *, rel_tol: float) -> bool:
    for form in _forms(value, aliases):
        gold = parse_amount(form)
        if gold is None:
            continue
        for amount in text_amounts(raw_text):
            if gold == 0:
                if abs(amount) < 1:
                    return True
            elif abs(amount - gold) / abs(gold) <= rel_tol:
                return True
    return False


def gold_in_text(
    field_type: str,
    value: Any,
    aliases: tuple[str, ...] = (),
    *,
    text: str,
    url: str = "",
    cues: tuple[str, ...] = (),
) -> bool:
    raw = text or ""
    norm = squad_norm(raw)
    if cues and not any(phrase_in(squad_norm(c), norm) for c in cues):
        return False
    if field_type == "person":
        return _match_person(value, aliases, norm)
    if field_type == "entity":
        return _match_entity(value, aliases, norm)
    if field_type == "list":
        return _match_list(value, aliases, norm)
    if field_type == "year":
        return _match_year(value, aliases, raw)
    if field_type == "country":
        return _match_country(value, aliases, norm, raw)
    if field_type == "domain":
        return _match_domain(value, aliases, raw, url)
    if field_type == "exact_id":
        return _match_exact_id(value, aliases, raw)
    if field_type == "money":
        return _match_amount(value, aliases, raw, rel_tol=0.02)
    if field_type == "numeric_band":
        return _match_amount(value, aliases, raw, rel_tol=0.15)
    raise ValueError(f"unknown field_type {field_type!r}")
