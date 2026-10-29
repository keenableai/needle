from datetime import UTC, datetime

from needle.coding.generate import run_generate
from needle.coding.models import DocHost
from needle.coding.sources import english_indexes, page_body, parse_llms

NOW = datetime(2026, 7, 4, 12, 0, tzinfo=UTC)
HOUR = NOW.replace(minute=0)
HOST = DocHost("example", "Example", "https://docs.example.com/llms.txt")
GOOD_QUERY = "example plan caps and burst windows for api requests"
BODY = "Plans cap requests per minute and burst. " * 20

ROOT = """
# Docs
- [v2 (10 pages)](https://docs.example.com/_llms/v2.txt): current
- [Legacy Page](https://docs.example.com/legacy-page.md): ignored because an index exists
"""

INDEX = """
# v2
- [Introduction](https://docs.example.com/introduction.md): a short welcome
- [Rate Limits](https://docs.example.com/rate-limits.md): Rate limits for plans and API requests
- [Batch Jobs](https://docs.example.com/features/batch-jobs.md): Submit many urls and poll the job
- [spec](https://docs.example.com/openapi.json)
"""


def _markdown(title: str) -> str:
    return f"> ## Documentation Index\n> Fetch the index.\n\n# {title}\n\n{BODY}"


class FakeDocs:
    def __init__(self, pages):
        self._pages = pages

    async def fetch_text(self, url):
        return self._pages.get(url)


class FakeLLM:
    def __init__(self, reply):
        self._reply = reply

    async def complete(self, prompt, *, max_tokens, reasoning_effort):
        if "Batch Jobs" in prompt:
            return "example submit many urls and poll until each page is done", None
        return self._reply, None


def _client():
    return FakeDocs(
        {
            HOST.llms_url: ROOT,
            "https://docs.example.com/_llms/v2.txt": INDEX,
            "https://docs.example.com/rate-limits.md": _markdown("Rate Limits"),
            "https://docs.example.com/features/batch-jobs.md": _markdown("Batch Jobs"),
        }
    )


async def test_generate_emits_title_and_task_rows_from_the_current_index():
    rows, stats = await run_generate(
        client=_client(),
        llm=FakeLLM(GOOD_QUERY),
        hour_ts=HOUR,
        hosts=(HOST,),
        per_host=2,
        seed=0,
    )
    assert stats.title_rows == 2
    assert stats.task_rows == 2
    assert stats.candidates == 2
    titles = [r for r in rows if r["query_origin"]["bucket"] == "title"]
    tasks = [r for r in rows if r["query_origin"]["bucket"] == "task"]
    assert {r["query_text"] for r in titles} == {
        "Example Rate Limits",
        "Example Features Batch Jobs",
    }
    assert {r["query_text"] for r in tasks} == {
        GOOD_QUERY,
        "example submit many urls and poll until each page is done",
    }
    assert all(r["gold"]["ids"]["page"] == r["gold"]["item_key"] for r in rows)
    assert "docs.example.com/legacy-page" not in {r["gold"]["item_key"] for r in rows}
    assert "docs.example.com/introduction" not in {r["gold"]["item_key"] for r in rows}


async def test_generate_drops_a_leaky_task_and_skips_the_title():
    rows, stats = await run_generate(
        client=_client(),
        llm=FakeLLM("example rate limits for the public api"),
        hour_ts=HOUR,
        hosts=(HOST,),
        per_host=2,
        seed=0,
    )
    kept = {r["gold"]["item_key"] for r in rows}
    assert "docs.example.com/rate-limits" not in kept
    assert "docs.example.com/features/batch-jobs" in kept
    assert stats.task_rejected == 1


async def test_generate_selection_varies_with_seed():
    pages = "\n".join(
        f"- [Widget {n}](https://docs.example.com/widget-{n}.md): a distinct widget page"
        for n in range(8)
    )
    markdown = {
        f"https://docs.example.com/widget-{n}.md": _markdown(f"Widget {n}") for n in range(8)
    }

    async def picked(seed):
        rows, _ = await run_generate(
            client=FakeDocs({HOST.llms_url: pages, **markdown}),
            llm=FakeLLM(GOOD_QUERY),
            hour_ts=HOUR,
            hosts=(HOST,),
            per_host=2,
            seed=seed,
        )
        return {r["gold"]["item_key"] for r in rows if r["query_origin"]["bucket"] == "title"}

    assert await picked(1) != await picked(2)


def test_parse_llms_keeps_pages_and_indexes_and_skips_generic_titles():
    pages, indexes = parse_llms(ROOT + INDEX, product="Example", base_url=HOST.llms_url)
    assert indexes == ["https://docs.example.com/_llms/v2.txt"]
    paths = {page.path for page in pages}
    assert "/rate-limits" in paths
    assert "/features/batch-jobs" in paths
    assert "/introduction" not in paths
    assert all(not path.endswith(".json") for path in paths)


def test_page_body_drops_the_index_blockquote_and_heading():
    assert page_body(_markdown("Rate Limits")).startswith("Plans cap requests")


def test_parse_llms_keeps_the_english_page_and_its_section():
    text = """
# Docs
- [en](https://docs.example.com/_llms/en/v2.txt)
- [fr deep](https://docs.example.com/_llms/fr/v2/documentation.txt)
### API Reference
#### Domains
- [Verify Domain](https://docs.example.com/docs/api-reference/domains/verify-domain.md): Verify it
- [Vérifier](https://docs.example.com/fr/docs/verify.md): page française
"""
    pages, indexes = parse_llms(text, product="Example", base_url=HOST.llms_url)
    assert english_indexes(indexes) == ["https://docs.example.com/_llms/en/v2.txt"]
    assert [page.path for page in pages] == ["/docs/api-reference/domains/verify-domain"]
    assert pages[0].section == "Domains"


async def test_generate_follows_the_english_index_not_the_deeper_translation():
    root = """
- [en](https://docs.example.com/_llms/en/v2.txt)
- [fr](https://docs.example.com/_llms/fr/v2/documentation.txt)
"""
    english = "- [Rate Limits](https://docs.example.com/rate-limits.md): plans and burst"
    french = "- [Veille](https://docs.example.com/fr/use-cases/veille.md): page française"
    rows, _stats = await run_generate(
        client=FakeDocs(
            {
                HOST.llms_url: root,
                "https://docs.example.com/_llms/en/v2.txt": english,
                "https://docs.example.com/_llms/fr/v2/documentation.txt": french,
                "https://docs.example.com/rate-limits.md": _markdown("Rate Limits"),
            }
        ),
        llm=FakeLLM(GOOD_QUERY),
        hour_ts=HOUR,
        hosts=(HOST,),
        per_host=1,
        seed=1,
    )
    assert {row["gold"]["path"] for row in rows} == {"/rate-limits"}


async def test_generate_keeps_pages_listed_beside_a_nested_index():
    root = "- [tree](https://docs.example.com/_llms/v2.txt)"
    mixed = """
- [Rate Limits](https://docs.example.com/rate-limits.md): plans and burst
- [nested](https://docs.example.com/_llms/v2/features.txt)
"""
    nested = "- [Batch Jobs](https://docs.example.com/features/batch-jobs.md): submit many urls"
    rows, stats = await run_generate(
        client=FakeDocs(
            {
                HOST.llms_url: root,
                "https://docs.example.com/_llms/v2.txt": mixed,
                "https://docs.example.com/_llms/v2/features.txt": nested,
                "https://docs.example.com/rate-limits.md": _markdown("Rate Limits"),
                "https://docs.example.com/features/batch-jobs.md": _markdown("Batch Jobs"),
            }
        ),
        llm=FakeLLM(GOOD_QUERY),
        hour_ts=HOUR,
        hosts=(HOST,),
        per_host=2,
        seed=1,
    )
    assert stats.candidates == 2
    assert {row["gold"]["path"] for row in rows} == {"/rate-limits", "/features/batch-jobs"}


async def test_generate_skips_a_repeated_query_and_fills_the_slot():
    pages = "\n".join(
        f"- [{name}](https://docs.example.com/{name.lower()}.md): a {name.lower()} page"
        for name in ("Alpha", "Beta", "Gamma")
    )
    markdown = {
        f"https://docs.example.com/{name.lower()}.md": _markdown(name)
        for name in ("Alpha", "Beta", "Gamma")
    }

    class Shared:
        async def complete(self, prompt, *, max_tokens, reasoning_effort):
            if "Gamma" in prompt:
                return "example finishes the distinct job in the public api", None
            return GOOD_QUERY, None

    rows, stats = await run_generate(
        client=FakeDocs({HOST.llms_url: pages, **markdown}),
        llm=Shared(),
        hour_ts=HOUR,
        hosts=(HOST,),
        per_host=2,
        seed=0,
    )
    tasks = [row for row in rows if row["query_origin"]["bucket"] == "task"]
    assert stats.task_rows == 2
    assert stats.short_hosts == 0
    assert len({row["query_text"] for row in tasks}) == 2
    assert "/gamma" in {row["gold"]["path"] for row in tasks}


async def test_generate_title_slice_does_not_call_the_llm():
    class Boom:
        async def complete(self, prompt, *, max_tokens, reasoning_effort):
            raise AssertionError("title slice must not call the llm")

    rows, stats = await run_generate(
        client=_client(),
        llm=Boom(),
        hour_ts=HOUR,
        hosts=(HOST,),
        per_host=1,
        seed=0,
        slices=("title",),
    )
    assert stats.task_rows == 0
    assert stats.title_rows == 1
    assert rows[0]["query_origin"]["bucket"] == "title"
