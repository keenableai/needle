import asyncio

import pytest

from keenbench.findallmcp.harness import _blocked_registry, _guard_registry
from keenbench.shared.agent import Tool


def test_blocked_registry_walks_nested_args():
    assert (
        _blocked_registry({"urls": ["https://efts.sec.gov/LATEST/search-index?q=%22S-1%22"]})
        == "efts.sec.gov"
    )
    assert (
        _blocked_registry({"queries": ["ok query", "https://HN.Algolia.com/api/v1/search"]})
        == "hn.algolia.com"
    )
    assert _blocked_registry({"nested": {"urls": ["https://data.sec.gov/submissions/x.json"]}}) == (
        "data.sec.gov"
    )
    assert _blocked_registry({"url": "https://www.sec.gov/cgi-bin/browse-edgar?type=S-1"}) == (
        "sec.gov/cgi-bin"
    )
    assert (
        _blocked_registry({"urls": ["https://www.sec.gov/Archives/edgar/data/320193/doc.htm"]})
        is None
    )
    args = {"urls": ["https://news.ycombinator.com/item?id=1"], "live": True}
    assert _blocked_registry(args) is None


def test_blocked_registry_covers_fda_github_nvd():
    blocked = [
        "https://api.fda.gov/food/enforcement.json?search=report_date:[20260611+TO+20260711]",
        "https://api.github.com/search/repositories?q=created:2026-06-11..2026-07-11",
        "https://github.com/search?q=stars%3A%3E3000&type=repositories",
        "https://services.nvd.nist.gov/rest/json/cves/2.0?hasKev",
        "https://nvd.nist.gov/vuln/search/results?form_type=Advanced",
        "https://www.cisa.gov/known-exploited-vulnerabilities-catalog",
        "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json",
        "https://www.saferproducts.gov/RestWebServices/Recall?RecallDateStart=2026-06-12",
        "https://www.cpsc.gov/Recalls/2026/Best-Buy-Recalls-Insignia-Gas-Ranges",
        "https://cpsc.gov/en/recalls",
        "https://www.cpsc.gov/Newsroom/News-Releases/2026/some-release",
        "https://api.usaspending.gov/api/v2/search/spending_by_award/",
        "https://www.usaspending.gov/search",
    ]
    for url in blocked:
        assert _blocked_registry({"urls": [url]}) is not None, url
    allowed = [
        "https://www.fda.gov/safety/recalls-market-withdrawals-safety-alerts/some-recall",
        "https://api.github.com/repos/langchain-ai/openwiki",
        "https://github.com/langchain-ai/openwiki",
        "https://nvd.nist.gov/vuln/detail/CVE-2026-34908",
        "https://www.cisa.gov/news-events/cybersecurity-advisories/aa26-190a",
    ]
    for url in allowed:
        assert _blocked_registry({"urls": [url]}) is None, url


def test_guard_registry_blocks_and_passes_through():
    async def fn(**kwargs):
        return "ok"

    tool = _guard_registry(
        Tool(name="fetch_web_pages", description="", function=fn, parameters_schema={})
    )
    with pytest.raises(RuntimeError, match="hacker-news.firebaseio.com"):
        asyncio.run(tool.function(urls=["https://hacker-news.firebaseio.com/v0/item/1.json"]))
    assert asyncio.run(tool.function(urls=["https://news.ycombinator.com/show"])) == "ok"
    assert tool.name == "fetch_web_pages"
