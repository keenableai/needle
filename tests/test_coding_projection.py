from needle.coding.models import DocPage
from needle.coding.projection import (
    clean_task_query,
    locator_leaks,
    product_missing,
    task_query_ok,
    title_query,
    title_span_leaks,
)

PAGE = DocPage(
    product="Example",
    title="Rate Limits",
    description="Rate limits for plans and API requests",
    host="docs.example.com",
    path="/rate-limits",
    body="Plans cap requests per minute and burst. " * 20,
)


def test_title_query_prefixes_the_product_and_the_section():
    assert title_query(PAGE) == "Example Rate Limits"
    sectioned = DocPage(
        product="Resend",
        title="Verify Domain",
        description="Verify a domain",
        host="resend.com",
        path="/docs/api-reference/domains/verify-domain",
        section="Domains",
    )
    assert title_query(sectioned) == "Resend Domains Verify Domain"
    flat = DocPage(
        product="Resend",
        title="Verify Domain",
        description="Verify an existing domain",
        host="resend.com",
        path="/docs/api-reference/domains/verify-domain",
    )
    assert title_query(flat) == "Resend API Reference Domains Verify Domain"
    named = DocPage(
        product="Example",
        title="What is Example?",
        description="",
        host="docs.example.com",
        path="/what-is-example",
    )
    assert title_query(named) == "What is Example?"


def test_clean_task_query_handles_sentinel_and_noise():
    assert clean_task_query("NO_DISTINCT_QUERY") is None
    assert clean_task_query("") is None
    assert clean_task_query("  example plan caps and burst windows for api requests  ") == (
        "example plan caps and burst windows for api requests"
    )


def test_title_span_leaks_on_the_whole_short_heading():
    assert title_span_leaks("example rate limits for the public api", PAGE.title)
    assert not title_span_leaks("example plan caps and burst windows for api requests", PAGE.title)


def test_task_query_ok_requires_the_product_and_hides_the_locator():
    good = "example plan caps and burst windows for api requests"
    assert task_query_ok(good, page=PAGE)
    assert product_missing("plan caps and burst windows for api requests", PAGE.product)
    assert not task_query_ok("plan caps and burst windows for api requests", page=PAGE)
    assert locator_leaks("example docs.example.com/rate-limits burst windows", PAGE)
    assert locator_leaks("example rate-limits burst windows for requests", PAGE)
    assert not task_query_ok("example rate limits for the public api", page=PAGE)
    assert not task_query_ok("example burst", page=PAGE)
    assert not task_query_ok("example plan caps and burst", page=PAGE)
    long = "example plan caps and burst windows for api requests across every paid tier today now"
    assert not task_query_ok(long, page=PAGE)
    assert not task_query_ok("how does example cap burst windows for api requests", page=PAGE)
    crawl = DocPage(
        product="Example",
        title="Crawl",
        description="Crawl a site",
        host="docs.example.com",
        path="/features/crawl",
        body="Walk every linked page. " * 20,
    )
    assert title_span_leaks("example crawl a site and wait for pages", crawl.title)
    assert not task_query_ok("example crawl a site and wait for pages", page=crawl)
    assert task_query_ok("example walk every linked page and wait", page=crawl)
