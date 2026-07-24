import re

from keenbench.scholar.models import Paper
from keenbench.shared.prompts import render_prompt

BODY_EXCERPT_CHARS = 6000
MIN_TITLE_WORDS = 4
MIN_QUERY_WORDS = 3
MIN_CLUE_WORDS = 8
MIN_TOT_WORDS = 12
MAX_TOT_TITLE_OVERLAP = 2
MIN_NOVEL_TOKENS = 2
MIN_SPECIFIC_CONTENT = 5

STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "into",
        "is",
        "of",
        "on",
        "or",
        "the",
        "to",
        "via",
        "with",
        "using",
        "based",
        "toward",
        "towards",
        "over",
        "under",
        "this",
        "that",
        "these",
        "those",
        "we",
        "our",
        "it",
        "its",
        "their",
        "study",
        "paper",
        "approach",
        "method",
        "methods",
        "results",
        "novel",
        "new",
        "efficient",
        "effective",
        "robust",
        "improved",
        "improving",
        "learning",
        "model",
        "models",
        "analysis",
        "framework",
        "system",
        "systems",
    }
)

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-]*")
_LATEX_RE = re.compile(r"\$[^$]*\$|\\[a-zA-Z]+\{[^}]*\}|\\[a-zA-Z]+")
_PUNCT_RE = re.compile(r"[^a-zA-Z0-9\s\-]")
_DISTINCTIVE_RE = re.compile(r"\d|[A-Z]{2,}|[a-z][A-Z]|[A-Za-z]{3,}-[A-Za-z]{3,}")
_BAD_ANCHOR_RE = re.compile(
    r"\bet al\b"
    r"|\b(?:table|figure|fig|section|appendix|theorem|lemma|corollary|proposition)\s*\.?\s*\d"
    r"|\bsupplementary\b",
    re.IGNORECASE,
)
_PRECISE_VALUE_RE = re.compile(r"\d+\.\d+|\d{5,}")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-]+")
_COINED_WORD_RE = re.compile(r"^(?:[A-Z]{2,}|[A-Za-z0-9\-]*[a-z][A-Z])[A-Za-z0-9\-]*$")


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def content_tokens(text: str) -> set[str]:
    return {t for t in _tokens(text) if t not in STOPWORDS and len(t) > 2}


def degrade_title(title: str) -> str | None:
    text = _LATEX_RE.sub(" ", title)
    text = _PUNCT_RE.sub(" ", text)
    words = text.lower().split()
    if len(words) < MIN_TITLE_WORDS:
        return None
    return " ".join(words)


def title_is_specific(title: str) -> bool:
    if _DISTINCTIVE_RE.search(title):
        return True
    return len(content_tokens(title)) >= MIN_SPECIFIC_CONTENT


def clean_body_query(text: str | None) -> str | None:
    text = (text or "").strip()
    if not text:
        return None
    cleaned = text.splitlines()[0].strip().strip("'").strip()
    if len(cleaned) >= 2 and cleaned[0] == '"' and cleaned[-1] == '"' and '"' not in cleaned[1:-1]:
        cleaned = cleaned[1:-1].strip()
    if cleaned.count('"') % 2:
        cleaned = " ".join(cleaned.replace('"', " ").split())
    if not cleaned or "NO_DISTINCT_QUERY" in cleaned.upper():
        return None
    return cleaned


def body_has_bad_anchor(query: str) -> bool:
    return bool(_BAD_ANCHOR_RE.search(query))


def body_query_ok(query: str, *, title: str, abstract: str) -> bool:
    q_tokens = content_tokens(query)
    if len(query.split()) < MIN_QUERY_WORDS or not q_tokens:
        return False
    metadata = content_tokens(title) | content_tokens(abstract)
    novel = q_tokens - metadata
    return len(novel) >= MIN_NOVEL_TOKENS


def clue_query_ok(query: str, *, title: str, abstract: str) -> bool:
    if len(query.split()) < MIN_CLUE_WORDS:
        return False
    return body_query_ok(query, title=title, abstract=abstract)


def tot_query_ok(query: str, *, title: str, abstract: str) -> bool:
    if len(query.split()) < MIN_TOT_WORDS or '"' in query:
        return False
    if _PRECISE_VALUE_RE.search(query):
        return False
    title_tokens = content_tokens(title)
    if len(content_tokens(query) & title_tokens) > MAX_TOT_TITLE_OVERLAP:
        return False
    metadata = title_tokens | content_tokens(abstract)
    coined = {w.lower() for w in _WORD_RE.findall(query) if _COINED_WORD_RE.match(w)}
    return not (coined & metadata)


LLM_QUERY_SPECS = {
    "body": ("body_query.jinja", body_query_ok),
    "clue": ("clue_query.jinja", clue_query_ok),
    "tot": ("tot_query.jinja", tot_query_ok),
}
LLM_BUCKETS = tuple(LLM_QUERY_SPECS)


def query_ok(bucket: str, query: str, *, title: str, abstract: str) -> bool:
    return LLM_QUERY_SPECS[bucket][1](query, title=title, abstract=abstract)


def body_excerpt(body: str) -> str:
    return body[:BODY_EXCERPT_CHARS]


def build_query_prompt(bucket: str, paper: Paper, body: str) -> str:
    return render_prompt(
        __package__,
        LLM_QUERY_SPECS[bucket][0],
        title=paper.title,
        abstract=paper.abstract[:1500],
        body=body_excerpt(body),
    )
