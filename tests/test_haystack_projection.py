from needle.haystack.models import SUITE_SPECS, DeepDoc
from needle.haystack.projection import (
    DEPTH_FLOOR,
    EXCERPT_CHARS,
    HEAD_CHARS,
    MIN_DOC_CHARS,
    deep_excerpt,
    parse_haystack_reply,
    question_ok,
    syntax_query,
)

QUESTION = "who led the acme deep sea mapping expedition for the research council"


def _doc(text, title="Acme expedition report"):
    return DeepDoc(
        suite="gov",
        title=title,
        url="https://example.gov/doc",
        published="2026-01-15",
        text=text,
        doc_keys={},
    )


def test_deep_excerpt_rejects_short_docs():
    assert deep_excerpt("x" * (MIN_DOC_CHARS - 1), seed=0, url="https://a") is None


def test_deep_excerpt_starts_past_floor_and_fits():
    text = "x" * 40_000
    excerpt, depth_pct = deep_excerpt(text, seed=7, url="https://a")
    assert len(excerpt) == EXCERPT_CHARS
    assert depth_pct >= int(DEPTH_FLOOR * 100)
    assert depth_pct <= round(100 * (len(text) - EXCERPT_CHARS) / len(text))


def test_deep_excerpt_is_seed_and_url_deterministic():
    text = "".join(str(i % 10) for i in range(40_000))
    assert deep_excerpt(text, seed=7, url="https://a") == deep_excerpt(
        text, seed=7, url="https://a"
    )
    assert deep_excerpt(text, seed=7, url="https://a") != deep_excerpt(
        text, seed=8, url="https://a"
    )
    assert deep_excerpt(text, seed=7, url="https://a") != deep_excerpt(
        text, seed=7, url="https://b"
    )


def test_parse_haystack_reply_happy_and_first_line():
    assert parse_haystack_reply("person || Maria Ellsworth || who led the dig\nignored") == (
        "person",
        "Maria Ellsworth",
        "who led the dig",
    )
    assert parse_haystack_reply("ENTITY || X Corp || who built it")[0] == "entity"


def test_parse_haystack_reply_rejects_sentinel_and_malformed():
    assert parse_haystack_reply("NO_DEEP_FACT") is None
    assert parse_haystack_reply(None) is None
    assert parse_haystack_reply("") is None
    assert parse_haystack_reply("person || only two fields") is None
    assert parse_haystack_reply("a || b || c || d") is None
    assert parse_haystack_reply("person ||  || question") is None


def _ok(answer="Maria Ellsworth", field_type="person", question=QUESTION, head="", deep=None):
    deep = deep if deep is not None else f"the survey was led by {answer} across three seasons"
    text = (head or "intro ") * 1 + "x" * HEAD_CHARS + deep
    return question_ok(question, answer, field_type, doc=_doc(text), excerpt=deep)


def test_question_ok_happy_path():
    assert _ok() is True


def test_question_ok_rejects_unknown_and_excluded_types():
    assert _ok(field_type="country") is False
    assert _ok(field_type="domain") is False
    assert _ok(field_type="made_up") is False


def test_question_ok_rejects_bad_lengths():
    assert _ok(question="too short question here") is False
    assert _ok(question="word " * 26) is False
    assert _ok(answer="one two three four five six seven eight nine") is False
    assert _ok(answer="x" * 81, deep="span " + "x" * 81 + " end") is False


def test_question_ok_requires_verbatim_answer_in_excerpt():
    assert _ok(deep="the survey was led by someone else entirely") is False


def test_question_ok_rejects_answer_leaking_into_question():
    assert (
        _ok(question="why did maria ellsworth lead the acme deep sea mapping expedition") is False
    )


def test_question_ok_rejects_identifier_leaks():
    assert _ok(question="which rule 0000004977-25-000067 covers the acme deep sea survey") is False
    assert _ok(question="does paper 2403.12345 describe the acme deep sea mapping work") is False
    assert _ok(question="what does document 2026-01234 say about acme deep sea mapping") is False
    assert _ok(question="what does section 4 require for acme deep sea mapping surveys") is False


def test_question_ok_rejects_answers_findable_from_head():
    head = "report by Maria Ellsworth on deep sea mapping "
    assert _ok(head=head) is False


def test_question_ok_validates_typed_values():
    assert _ok(answer="1987", field_type="year", deep="first charted in 1987 by the crew") is True
    assert _ok(answer="around then", field_type="year") is False
    assert (
        _ok(answer="$4.2 million", field_type="money", deep="a budget of $4.2 million was spent")
        is True
    )
    assert _ok(answer="several", field_type="numeric_band", deep="several ships sailed") is False


def test_syntax_query_variants():
    spec = SUITE_SPECS["gov"]
    assert syntax_query(QUESTION, "plain", site=spec.site, published="2026-01-15") == QUESTION
    assert (
        syntax_query(QUESTION, "site", site=spec.site, published="2026-01-15")
        == f"{QUESTION} site:federalregister.gov"
    )
    dated = syntax_query(QUESTION, "date", site=spec.site, published="2026-01-15")
    assert "after:2025-12-01" in dated and "before:2026-03-01" in dated
    assert syntax_query(QUESTION, "date", site=spec.site, published="") == QUESTION


def test_wiki_cycle_has_no_date_syntax():
    assert "date" not in SUITE_SPECS["wiki"].syntax_cycle
    assert set(SUITE_SPECS["wiki"].syntax_cycle) == {"plain", "site"}
