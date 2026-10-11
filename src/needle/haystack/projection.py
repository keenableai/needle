import re
import zlib
from datetime import date

from needle.finance.canon import YEAR_RE, gold_in_text, parse_amount, phrase_in, squad_norm
from needle.finance.projection import ADSH_RE
from needle.haystack.models import HAYSTACK_FIELD_TYPES, DeepDoc, SuiteSpec
from needle.legal.projection import CFR_LEAK_RE, date_operators
from needle.shared.prompts import clean_llm_line, render_prompt

QUESTION_TEMPLATE = "haystack_question.jinja"
SENTINEL = "NO_DEEP_FACT"
MIN_DOC_CHARS = 30_000
EXCERPT_CHARS = 7_000
HEAD_CHARS = 4_000
DEPTH_FLOOR = 0.55
MIN_QUESTION_WORDS = 6
MAX_QUESTION_WORDS = 25
MAX_ANSWER_WORDS = 8
MAX_ANSWER_CHARS = 80

ARXIV_LEAK_RE = re.compile(r"\b\d{4}\.\d{4,5}\b")
FR_DOCNUM_LEAK_RE = re.compile(r"\b\d{4}-\d{4,6}\b")
LEAK_RES = (ADSH_RE, ARXIV_LEAK_RE, FR_DOCNUM_LEAK_RE, CFR_LEAK_RE)


def deep_excerpt(text: str, *, seed: int, url: str) -> tuple[str, int] | None:
    if len(text) < MIN_DOC_CHARS:
        return None
    usable = len(text) - EXCERPT_CHARS
    lo = max(HEAD_CHARS, int(DEPTH_FLOOR * len(text)))
    if lo > usable:
        return None
    key = (seed ^ zlib.crc32(url.encode())) & 0x7FFFFFFF
    start = lo + key % (usable - lo + 1)
    return text[start : start + EXCERPT_CHARS], round(100 * start / len(text))


def build_haystack_prompt(doc: DeepDoc, excerpt: str, *, spec: SuiteSpec) -> str:
    return render_prompt(
        __package__,
        QUESTION_TEMPLATE,
        title=doc.title,
        source=spec.source_label,
        published=doc.published,
        excerpt=excerpt,
    )


def parse_haystack_reply(text: str | None) -> tuple[str, str, str] | None:
    line = clean_llm_line(text, sentinel=SENTINEL)
    if line is None:
        return None
    parts = [p.strip() for p in line.split("||")]
    if len(parts) != 3 or not all(parts):
        return None
    field_type, answer, question = parts
    return field_type.lower(), answer, question


def _value_ok(field_type: str, answer: str) -> bool:
    if field_type == "year":
        return YEAR_RE.fullmatch(answer.strip()) is not None
    if field_type in ("money", "numeric_band"):
        return parse_amount(answer) is not None
    return True


def question_ok(question: str, answer: str, field_type: str, *, doc: DeepDoc, excerpt: str) -> bool:
    if field_type not in HAYSTACK_FIELD_TYPES:
        return False
    if not MIN_QUESTION_WORDS <= len(question.split()) <= MAX_QUESTION_WORDS:
        return False
    if not 1 <= len(answer.split()) <= MAX_ANSWER_WORDS or len(answer) > MAX_ANSWER_CHARS:
        return False
    if not _value_ok(field_type, answer):
        return False
    if " ".join(answer.lower().split()) not in " ".join(excerpt.lower().split()):
        return False
    norm_answer = squad_norm(answer)
    if not norm_answer or phrase_in(norm_answer, squad_norm(question)):
        return False
    if any(leak.search(question) for leak in LEAK_RES):
        return False
    head = f"{doc.title} {doc.text[:HEAD_CHARS]}"
    return not gold_in_text(field_type, answer, (), text=head, url=doc.url)


def syntax_query(base: str, syntax: str, *, site: str, published: str) -> str:
    if syntax == "site":
        return f"{base} site:{site}"
    if syntax == "date":
        try:
            pub = date.fromisoformat(published)
        except ValueError:
            return base
        return f"{base} {date_operators(pub)}"
    return base
