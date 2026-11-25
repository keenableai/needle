import re
from urllib.parse import urlsplit

from needle.coding.models import Doc
from needle.shared.prompts import clean_llm_line, render_prompt

TEMPLATES = {"api": "api_query.jinja", "issue": "issue_query.jinja", "qa": "qa_query.jinja"}
SYNTAX_CYCLES = {
    "api": ("plain", "site"),
    "issue": ("plain", "quoted", "plain", "site"),
    "qa": ("plain", "site"),
}
WORD_LIMITS = {"api": (4, 12), "issue": (5, 16), "qa": (4, 12)}
SPAN_WORDS = (2, 12)
MIN_NOVEL_WORDS = 2
MIN_NOVEL_CHARS = 4

QUOTED_SPAN_RE = re.compile(r'"([^"]+)"')
CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
WORD_RE = re.compile(r"[a-z][a-z0-9_+#]*")


def build_prompt(doc: Doc) -> str:
    return render_prompt(
        __package__,
        TEMPLATES[doc.doc_type],
        doc=doc,
        project=doc.context.rsplit("/", 1)[-1],
    )


def clean_query(text: str | None) -> str | None:
    return clean_llm_line(text, sentinel="NO_DISTINCT_QUERY")


def mentions(query: str, name: str) -> bool:
    lowered = query.lower()
    forms = {name, name.replace("_", " "), CAMEL_RE.sub(" ", name)}
    return any(
        re.search(rf"(?<![a-z0-9]){re.escape(form.lower().strip())}(?![a-z0-9])", lowered)
        for form in forms
        if form.strip()
    )


def _span_in_doc(query: str, doc: Doc) -> bool:
    spans = QUOTED_SPAN_RE.findall(query)
    if len(spans) != 1 or not SPAN_WORDS[0] <= len(spans[0].split()) <= SPAN_WORDS[1]:
        return False
    haystack = " ".join(f"{doc.title} {doc.text}".lower().split())
    return " ".join(spans[0].lower().split()) in haystack


def _words(text: str) -> list[str]:
    return WORD_RE.findall(text.lower())


def _rephrased(query: str, doc: Doc) -> bool:
    query_words, title_words = _words(query), _words(doc.title)
    if f" {' '.join(title_words)} " in f" {' '.join(query_words)} ":
        return False
    known = set(title_words) | set(_words(doc.context))
    body_words = set(_words(doc.text))
    novel = {
        w for w in query_words if len(w) >= MIN_NOVEL_CHARS and w not in known and w in body_words
    }
    return len(novel) >= MIN_NOVEL_WORDS


def _names_source(query: str, doc: Doc) -> bool:
    return any(mentions(query, name) for name in doc.context.split("/"))


def query_ok(query: str, doc: Doc) -> bool:
    lo, hi = WORD_LIMITS[doc.doc_type]
    if not lo <= len(query.split()) <= hi:
        return False
    if any(mentions(query, name) for name in doc.banned):
        return False
    if doc.doc_type == "api":
        return _names_source(query, doc)
    if doc.doc_type == "issue":
        return _names_source(query, doc) and _span_in_doc(query, doc)
    return _rephrased(query, doc)


def syntax_query(query: str, doc: Doc, syntax: str) -> str:
    if syntax == "quoted":
        return query
    stripped = " ".join(query.replace('"', " ").split())
    if syntax == "site":
        host = (urlsplit(doc.url).hostname or "").removeprefix("www.")
        return f"{stripped} site:{host}"
    return stripped
