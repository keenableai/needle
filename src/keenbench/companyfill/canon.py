import re
import string
import unicodedata
from functools import lru_cache
from typing import Any

import tldextract

LEGAL_SUFFIXES = frozenset(
    "incorporated inc corporation corp company co limited ltd llc plc gmbh ag sa nv se spa"
    " kk pte pty bv oyj ab as lp holding holdings group the".split()
)

RAW_COUNTRY_ALIASES = {
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

PUNCT_TABLE = str.maketrans(dict.fromkeys(string.punctuation, " "))
ARTICLES_RE = re.compile(r"\b(a|an|the)\b")
YEAR_RE = re.compile(r"\b(1[5-9]\d{2}|20\d{2})\b")
AMOUNT_RE = re.compile(
    r"(?P<paren>\()?[ \t]*(?P<sign_before>-)?[ \t]*(?P<currency>[$€£¥])?"
    r"[ \t]*(?P<sign_after>-)?[ \t]*"
    r"(?P<number>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"[ \t]*(?P<suffix>trillion|billion|million|thousand|tn|bn|mn|mm|[tbmk])?\b"
    r"[ \t]*(?(paren)\))",
    re.IGNORECASE,
)
AMOUNT_SCALES = {
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
    s = s.translate(PUNCT_TABLE)
    s = ARTICLES_RE.sub(" ", s)
    return " ".join(s.split())


cached_squad_norm = lru_cache(maxsize=4096)(squad_norm)

COUNTRY_ALIASES = {squad_norm(k): v for k, v in RAW_COUNTRY_ALIASES.items()}


def country_form_indexes() -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    long_forms: dict[str, set[str]] = {}
    short_forms: dict[str, set[str]] = {}
    for surface, canonical in COUNTRY_ALIASES.items():
        if len(surface.replace(" ", "")) <= 3:
            short_forms.setdefault(canonical, set()).add("".join(surface.split()).upper())
        else:
            long_forms.setdefault(canonical, set()).add(surface)
    return long_forms, short_forms


COUNTRY_LONG_FORMS, COUNTRY_SHORT_FORMS = country_form_indexes()


def strip_legal(value: Any) -> str:
    return " ".join(t for t in squad_norm(value).split() if t not in LEGAL_SUFFIXES)


TLD_EXTRACT = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)


def registrable_domain(value: Any) -> str:
    s = unicodedata.normalize("NFKC", str(value if value is not None else "")).strip().lower()
    s = re.sub(r"^[a-z][a-z0-9+.\-]*://", "", s)
    host = s.split("/")[0].split("?")[0].split(":")[0]
    return TLD_EXTRACT(host).top_domain_under_public_suffix or host


def phrase_in(phrase: str, text_norm: str) -> bool:
    return bool(phrase) and f" {phrase} " in f" {text_norm} "


def text_years(raw_text: str) -> set[int]:
    return {int(m) for m in YEAR_RE.findall(raw_text)}


def text_amounts(raw_text: str) -> list[float]:
    out = []
    for match in AMOUNT_RE.finditer(raw_text):
        suffix = match.group("suffix") or ""
        amount = float(match.group("number").replace(",", ""))
        amount *= AMOUNT_SCALES.get(suffix.lower(), 1.0)
        if match.group("paren") or match.group("sign_before") or match.group("sign_after"):
            amount = -amount
        out.append(amount)
    return out


def parse_amount(value: Any) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    amounts = text_amounts(str(value or ""))
    return amounts[0] if amounts else None


def _gold_forms(value: Any, aliases: tuple[str, ...]) -> list[Any]:
    return [f for f in [value, *aliases] if f not in (None, "")]


def _short_form_in(form_raw: str, raw_text: str) -> bool:
    pat = rf"(?<![A-Za-z0-9]){re.escape(form_raw)}(?![A-Za-z0-9])"
    return re.search(pat, raw_text) is not None


def _match_person(value: Any, aliases: tuple[str, ...], text_norm: str) -> bool:
    text_tokens = text_norm.split()
    for form in _gold_forms(value, aliases):
        form_norm = squad_norm(form)
        if phrase_in(form_norm, text_norm):
            return True
        name_tokens = form_norm.split()
        if len(name_tokens) < 2:
            continue
        given, surname = name_tokens[0], name_tokens[-1]
        if len(given) < 3:
            continue
        for i, token in enumerate(text_tokens):
            if token != surname:
                continue
            for preceding in text_tokens[max(0, i - 3) : i]:
                if len(preceding) >= 3 and (
                    preceding.startswith(given) or given.startswith(preceding)
                ):
                    return True
    return False


def _item_in_text(item_norm: str, text_norm: str) -> bool:
    if phrase_in(item_norm, text_norm):
        return True
    if " " not in item_norm and len(item_norm) > 3:
        alt = item_norm[:-1] if item_norm.endswith("s") else item_norm + "s"
        return phrase_in(alt, text_norm)
    return False


def _match_entity(value: Any, aliases: tuple[str, ...], text_norm: str) -> bool:
    stripped_text = " ".join(t for t in text_norm.split() if t not in LEGAL_SUFFIXES)
    return any(_item_in_text(strip_legal(f), stripped_text) for f in _gold_forms(value, aliases))


def _match_year(value: Any, aliases: tuple[str, ...], raw_text: str) -> bool:
    golds = set()
    for f in _gold_forms(value, aliases):
        try:
            golds.add(int(f))
        except (TypeError, ValueError):
            continue
    return bool(golds & text_years(raw_text))


GENERIC_COUNTRY_FORMS = frozenset({"state", "states", "union", "republic", "kingdom"})


def _match_country(value: Any, aliases: tuple[str, ...], text_norm: str, raw_text: str) -> bool:
    gold_norm = squad_norm(value)
    canonical = COUNTRY_ALIASES.get(gold_norm, gold_norm)
    long_forms = {canonical, gold_norm} | COUNTRY_LONG_FORMS.get(canonical, set())
    short_forms = set(COUNTRY_SHORT_FORMS.get(canonical, ()))
    for a in aliases:
        norm = squad_norm(a)
        if len(norm.replace(" ", "")) <= 3:
            short_forms.add(str(a).strip())
        elif norm and norm not in GENERIC_COUNTRY_FORMS:
            long_forms.add(norm)
    if any(phrase_in(f, text_norm) for f in long_forms):
        return True
    return any(_short_form_in(f, raw_text) for f in short_forms if f)


def _match_domain(value: Any, aliases: tuple[str, ...], raw_text: str, url: str) -> bool:
    text = raw_text.lower()
    for form in _gold_forms(value, aliases):
        dom = registrable_domain(form)
        if not dom or "." not in dom:
            continue
        if registrable_domain(url) == dom:
            return True
        if re.search(rf"(?<![a-z0-9-]){re.escape(dom)}(?![a-z0-9-])", text):
            return True
    return False


def _match_exact_id(value: Any, aliases: tuple[str, ...], raw_text: str, url: str) -> bool:
    compact = None
    for form in _gold_forms(value, aliases):
        norm = re.sub(r"[\s.\-]", "", str(form)).upper()
        if len(norm) < 2:
            continue
        if len(norm) <= 6:
            if _short_form_in(norm, raw_text):
                return True
        else:
            if compact is None:
                compact = re.sub(r"[^A-Z0-9]", "", f"{raw_text} {url}".upper())
            if norm in compact:
                return True
    return False


def _match_amount(value: Any, aliases: tuple[str, ...], raw_text: str, *, rel_tol: float) -> bool:
    amounts = text_amounts(raw_text)
    for form in _gold_forms(value, aliases):
        gold = parse_amount(form)
        if gold is None:
            continue
        for amount in amounts:
            if gold == 0:
                if abs(amount) < 1:
                    return True
            elif abs(amount - gold) / abs(gold) <= rel_tol:
                return True
    return False


FIELD_TYPES = frozenset(
    {"person", "entity", "year", "country", "domain", "exact_id", "money", "numeric_band"}
)


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
    if cues and not any(phrase_in(cached_squad_norm(c), norm) for c in cues):
        return False
    if field_type == "person":
        return _match_person(value, aliases, norm)
    if field_type == "entity":
        return _match_entity(value, aliases, norm)
    if field_type == "year":
        return _match_year(value, aliases, raw)
    if field_type == "country":
        return _match_country(value, aliases, norm, raw)
    if field_type == "domain":
        return _match_domain(value, aliases, raw, url)
    if field_type == "exact_id":
        return _match_exact_id(value, aliases, raw, url)
    if field_type == "money":
        return _match_amount(value, aliases, raw, rel_tol=0.02)
    if field_type == "numeric_band":
        return _match_amount(value, aliases, raw, rel_tol=0.15)
    raise ValueError(f"unknown field_type {field_type!r}")
