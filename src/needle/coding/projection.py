import re

from needle.coding.models import DocPage
from needle.coding.sources import path_section
from needle.shared.prompts import clean_llm_line, render_prompt

TASK_QUERY_TEMPLATE = "task_query.jinja"
BODY_EXCERPT_CHARS = 4000
MIN_BODY_CHARS = 180
MIN_QUERY_WORDS = 6
MAX_QUERY_WORDS = 14
TITLE_SPAN_WORDS = 4
QUESTION_OPENINGS = frozenset({"what", "why", "how"})

WORD_RE = re.compile(r"[a-z0-9]+")


def clean_task_query(text: str | None) -> str | None:
    return clean_llm_line(text, sentinel="NO_DISTINCT_QUERY")


def _words(text: str) -> list[str]:
    return WORD_RE.findall(text.lower())


def title_query(page: DocPage) -> str:
    section = page.section or path_section(page.path)
    parts: list[str] = []
    titled = _words(page.title)
    if page.product.lower() not in titled and page.product.lower() not in _words(section):
        parts.append(page.product)
    if section and section.lower() not in page.title.lower():
        parts.append(section)
    parts.append(page.title)
    return " ".join(parts)


def title_span_leaks(query: str, title: str, *, span: int = TITLE_SPAN_WORDS) -> bool:
    query_words = _words(query)
    title_words = _words(title)
    if len(title_words) == 1:
        return title_words[0] in query_words
    if len(title_words) < 2 or len(query_words) < 2:
        return False
    n = min(span, len(title_words))
    if len(query_words) < n:
        return False
    windows = {" ".join(title_words[i : i + n]) for i in range(len(title_words) - n + 1)}
    return any(" ".join(query_words[i : i + n]) in windows for i in range(len(query_words) - n + 1))


def product_missing(query: str, product: str) -> bool:
    return product.lower() not in _words(query)


def locator_leaks(query: str, page: DocPage) -> bool:
    folded = query.lower()
    if page.host in folded or page.path.lower() in folded:
        return True
    if "://" in folded or ".md" in folded:
        return True
    return "-" in page.slug and page.slug.lower() in folded


def task_query_ok(query: str, *, page: DocPage) -> bool:
    words = query.split()
    if not MIN_QUERY_WORDS <= len(words) <= MAX_QUERY_WORDS:
        return False
    if words[0].lower().strip("?.!:;,\"'") in QUESTION_OPENINGS:
        return False
    if product_missing(query, page.product):
        return False
    if locator_leaks(query, page):
        return False
    return not title_span_leaks(query, page.title)


def body_excerpt(page: DocPage) -> str:
    return page.body[:BODY_EXCERPT_CHARS]


def usable_body(page: DocPage) -> bool:
    return len(page.body.strip()) >= MIN_BODY_CHARS


def build_task_prompt(page: DocPage) -> str:
    return render_prompt(
        __package__,
        TASK_QUERY_TEMPLATE,
        product=page.product,
        title=page.title,
        body=body_excerpt(page),
    )
