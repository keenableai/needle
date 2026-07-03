import re

from keenbench.scholar.models import Paper
from keenbench.shared.prompts import render_prompt

BODY_QUERY_TEMPLATE = "body_query.jinja"
BODY_EXCERPT_CHARS = 6000
MIN_TITLE_WORDS = 4
MIN_QUERY_WORDS = 3
MIN_NOVEL_TOKENS = 2

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


def clean_body_query(text: str | None) -> str | None:
    text = (text or "").strip()
    if not text:
        return None
    cleaned = text.splitlines()[0].strip(" \"'")
    if not cleaned or "NO_DISTINCT_QUERY" in cleaned.upper():
        return None
    return cleaned


def body_query_ok(query: str, *, title: str, abstract: str) -> bool:
    q_tokens = content_tokens(query)
    if len(query.split()) < MIN_QUERY_WORDS or not q_tokens:
        return False
    metadata = content_tokens(title) | content_tokens(abstract)
    novel = q_tokens - metadata
    return len(novel) >= MIN_NOVEL_TOKENS


def body_excerpt(body: str) -> str:
    return body[:BODY_EXCERPT_CHARS]


def build_body_prompt(paper: Paper, body: str) -> str:
    return render_prompt(
        __package__,
        BODY_QUERY_TEMPLATE,
        title=paper.title,
        abstract=paper.abstract[:1500],
        body=body_excerpt(body),
    )
