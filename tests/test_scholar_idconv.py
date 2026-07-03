from keenbench.scholar.idconv import IdConverter


async def test_error_is_not_cached_and_allows_retry():
    conv = IdConverter()

    async def failing(method, url, **kwargs):
        return None, {"error_type": "http_error", "error_message": "boom"}

    conv._request_json = failing
    out = await conv.pmc_to_pmid(["111", "222"])
    assert out == {"111": None, "222": None}
    assert conv._cache == {}

    async def ok(method, url, **kwargs):
        return {"records": [{"pmcid": "PMC111", "pmid": "999"}]}, None

    conv._request_json = ok
    out2 = await conv.pmc_to_pmid(["111", "222"])
    assert out2["111"] == "999"
    assert out2["222"] is None
    assert conv._cache == {"111": "999", "222": None}
    await conv.aclose()


async def test_successful_resolutions_are_cached():
    conv = IdConverter()
    calls = 0

    async def ok(method, url, **kwargs):
        nonlocal calls
        calls += 1
        return {"records": [{"pmcid": "PMC777", "pmid": "42"}]}, None

    conv._request_json = ok
    assert (await conv.pmc_to_pmid(["777"]))["777"] == "42"
    assert (await conv.pmc_to_pmid(["777"]))["777"] == "42"
    assert calls == 1
    await conv.aclose()
