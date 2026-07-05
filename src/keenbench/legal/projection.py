import re
from datetime import date, timedelta

from keenbench.legal.models import COURT_PHRASES, Case, CodeSection
from keenbench.shared.prompts import render_prompt

CODE_QUERY_TEMPLATE = "code_query.jinja"
SECTION_EXCERPT_CHARS = 6000
MIN_CAPTION_WORDS = 3
MIN_QUERY_WORDS = 3
CASELAW_SITE = "courtlistener.com"
CODE_SITE = "law.cornell.edu"
DATE_WINDOW_DAYS = 45

CASELAW_SYNTAX_CYCLE = ("plain", "quoted", "plain", "site", "plain", "date")
CODE_SYNTAX_CYCLE = ("plain", "quoted", "plain", "site")

PARTY_SUFFIXES = frozenset(
    "incorporated inc corporation corp company co limited ltd llc llp lp plc pllc pc"
    " sa nv ag gmbh esquire esq attorney attorneys the a an".split()
)

GENERIC_PARTY_TOKENS = frozenset(
    "united states america state people commonwealth city county town village borough"
    " district board department secretary administrator commissioner director attorney"
    " general government federal national office bureau agency commission committee"
    " re parte rel estate matter application petition".split()
)

_VS_RE = re.compile(r"\s+vs?\.?\s+", re.IGNORECASE)
_ANNOTATION_RE = re.compile(r"\s+revisions?\s*:.*$", re.IGNORECASE)
_PUNCT_RE = re.compile(r"[^a-zA-Z0-9\s\-']")
_QUOTED_SPAN_RE = re.compile(r'"([^"]+)"')
_CFR_LEAK_RE = re.compile(
    r"\bc\.?f\.?r\b|\bu\.?s\.?c\b|§|\bsection\s+\d|\btitle\s+\d", re.IGNORECASE
)


def _clean_party(party: str) -> str:
    words = _PUNCT_RE.sub(" ", party).lower().split()
    kept = [w for w in words if w not in PARTY_SUFFIXES and not w.replace("-", "").isdigit()]
    return " ".join(kept)


def caption_parties(case_name: str) -> list[str]:
    cleaned = _ANNOTATION_RE.sub("", case_name).split(":", 1)[0]
    parts = _VS_RE.split(cleaned, maxsplit=1)
    return [p for p in (_clean_party(part) for part in parts) if p]


def party_tokens(case_name: str) -> list[str]:
    tokens = []
    for party in caption_parties(case_name):
        for token in party.split():
            if len(token) >= 4 and token not in GENERIC_PARTY_TOKENS:
                tokens.append(token)
    return list(dict.fromkeys(tokens))


def caption_query(case: Case) -> str | None:
    parties = caption_parties(case.case_name)
    if not parties:
        return None
    caption = " v ".join(parties[:2])
    court_phrase = COURT_PHRASES.get(case.court_id, "")
    query = f"{caption} {court_phrase}".strip()
    if len(query.split()) < MIN_CAPTION_WORDS or not party_tokens(case.case_name):
        return None
    return query


def caselaw_syntax_query(case: Case, base: str, syntax: str) -> str:
    if syntax == "quoted":
        parties = caption_parties(case.case_name)
        caption = " v ".join(parties[:2])
        court_phrase = COURT_PHRASES.get(case.court_id, "")
        return f'"{caption}" {court_phrase}'.strip()
    if syntax == "site":
        return f"{base} site:{CASELAW_SITE}"
    if syntax == "date":
        return f"{base} {date_operators(case.date_filed)}"
    return base


def date_operators(filed: date) -> str:
    after = filed - timedelta(days=DATE_WINDOW_DAYS)
    before = filed + timedelta(days=DATE_WINDOW_DAYS)
    return f"after:{after.isoformat()} before:{before.isoformat()}"


def code_syntax_query(base: str, syntax: str) -> str:
    if syntax == "quoted":
        return base
    stripped = " ".join(base.replace('"', " ").split())
    if syntax == "site":
        return f"{stripped} site:{CODE_SITE}"
    return stripped


def clean_code_query(text: str | None) -> str | None:
    text = (text or "").strip()
    if not text:
        return None
    cleaned = text.splitlines()[0].strip().strip("'").strip()
    if not cleaned or "NO_DISTINCT_QUERY" in cleaned.upper():
        return None
    return cleaned


def _section_number_forms(section: CodeSection) -> list[str]:
    forms = [section.section, section.part]
    if "." in section.section:
        forms.append(section.section.split(".", 1)[1])
    return [f for f in forms if f]


def code_query_ok(query: str, *, section: CodeSection) -> bool:
    if len(query.split()) < MIN_QUERY_WORDS:
        return False
    if _CFR_LEAK_RE.search(query):
        return False
    for form in _section_number_forms(section):
        if re.search(rf"(?<![\w.]){re.escape(form)}(?![\w.])", query):
            return False
    spans = _QUOTED_SPAN_RE.findall(query)
    if len(spans) != 1:
        return False
    span_words = spans[0].split()
    if not 2 <= len(span_words) <= 8:
        return False
    norm_text = " ".join(section.text.lower().split())
    return " ".join(spans[0].lower().split()) in norm_text


def section_excerpt(section: CodeSection) -> str:
    return section.text[:SECTION_EXCERPT_CHARS]


def build_code_prompt(section: CodeSection) -> str:
    return render_prompt(
        __package__,
        CODE_QUERY_TEMPLATE,
        heading=section.heading,
        text=section_excerpt(section),
    )
