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
