import pytest

from needle.shared.recall import ULTIMATE, classify_misses, recall_summary, ultimate_per_query
from needle.shared.search.errors import account_side


def _http(message):
    return {"error_type": "http_error", "error_message": message}


@pytest.mark.parametrize(
    "error",
    [
        _http('401: {"errors":[{"code":"general.unauthorized"}]}'),
        _http('402: {"error":"You have exceeded your credits limit"}'),
        _http("403: Forbidden"),
        _http(
            '400: {"type":"error","error":{"type":"invalid_request_error","message":"Your credit'
            ' balance is too low to access the Anthropic API. Please go to Plans & Billing"}}'
        ),
        _http(
            '429: {"error":{"message":"You have no credits remaining.","type":"insufficient_quota",'
            '"code":"credit_balance_exhausted"}}'
        ),
        {"error_type": "api_error", "error_message": "Invalid API key"},
        {"error_type": "api_error", "error_message": "missing api_key"},
        _http(
            '432: {"detail":{"error":"This request exceeds your plan\'s set usage limit. Please'
            ' upgrade your plan or contact support@tavily.com"}}'
        ),
        _http(
            '433: {"detail":{"error":"This request exceeds the pay-as-you-go limit. You can'
            ' increase your limit on the Tavily dashboard."}}'
        ),
        _http('400: {"message":"Not enough credits","statusCode":400}'),
        _http('429: {"error":"insufficient_credits"}'),
        _http('429: {"error":{"message":"You exceeded your current quota."}}'),
        {"error_type": "api_error", "error_message": "monthly usage limit reached"},
        _http(
            '429: {"error":{"code":"RATE_LIMIT_EXCEEDED","message":"Rate limit exceeded. Request a'
            ' higher limit at https://agent.tinyfish.ai/wallet"}}'
        ),
        _http("429: Too Many Requests"),
        _http(
            '429: {"type":"ErrorResponse","error":{"status":429,"code":"RATE_LIMITED",'
            '"detail":"Request rate limit exceeded for plan.","meta":{"plan":"Free",'
            '"rate_limit":1,"rate_current":1,"quota_limit":2000,"quota_current":13}}}'
        ),
    ],
)
def test_account_side_failures(error):
    assert account_side(error)


@pytest.mark.parametrize(
    "error",
    [
        _http('400: {"error":{"message":"Output blocked by content filtering policy"}}'),
        _http('400: {"message":"invalid domain","key_metadata":{"credits_remaining":991}}'),
        _http('422: {"message":"No search results available for query billing error resolution"}'),
        _http("503: Our servers are currently overloaded"),
        _http("500: Internal Server Error"),
        _http("500: usage limit exceeded upstream"),
        {"error_type": "transport", "error_message": "ReadTimeout"},
        {"error_type": "api_error", "error_message": "max_uses_exceeded"},
        {"error_type": "api_error", "error_message": "Bing didn't return any results."},
        {"error_type": "bad_json", "error_message": "Expecting value"},
    ],
)
def test_service_side_failures(error):
    assert not account_side(error)


def _pq(hit_rank=None, error=None):
    return {"hit_rank": hit_rank, "search_error": error, "results": [], "n_results": 0}


def test_recall_summary_zeroes_service_and_excludes_account_failures():
    per_query = [_pq(hit_rank=1), _pq(error=_http("503: down")), _pq(error=_http("401: no"))]
    summary = recall_summary(per_query, None)
    assert summary["recall_at_k"] == 0.5
    assert summary["num_scored"] == 2
    errors = ("search_errors", "account_errors", "service_errors")
    assert [summary[k] for k in errors] == [2, 1, 1]
    assert [pq["score"] for pq in per_query] == [1.0, 0.0, None]


def test_ultimate_counts_query_when_any_failure_is_service_side():
    entries = [_pq(error=_http("401: no")), _pq(error=_http("503: down"))]
    out = ultimate_per_query([entries], cap=5)
    assert out[0]["search_error"] == _http("503: down")
    assert recall_summary(out, None)["num_scored"] == 1
    both_account = ultimate_per_query([[_pq(error=_http("401: no"))] * 2], cap=5)
    assert recall_summary(both_account, None)["num_scored"] == 0


def test_classify_misses_counts_service_failures_and_skips_account_failures():
    service, account = _http("503: down"), _http("401: no")
    hit = dict(_pq(hit_rank=1), results=[{"url": "https://gold"}], n_results=1)
    query_outs = [
        [hit, _pq(error=service), _pq(error=account)],
        [_pq(error=service), _pq(error=service), _pq(error=account)],
        [_pq(error=account), _pq(error=account), _pq(error=account)],
    ]
    names = ["a", "b", "c"]
    engines_out = {name: {} for name in names}
    engines_out[ULTIMATE] = recall_summary(ultimate_per_query(query_outs, cap=5), None)
    classify_misses(query_outs, names, engines_out)
    assert engines_out["a"]["misses_system_specific"] == 0
    assert engines_out["a"]["misses_universal"] == 1
    assert engines_out["b"]["misses_system_specific"] == 1
    assert engines_out["b"]["misses_universal"] == 1
    assert engines_out["c"]["misses_system_specific"] == 0
    assert engines_out["c"]["misses_universal"] == 0
    assert engines_out[ULTIMATE]["num_scored"] == 2
    assert engines_out[ULTIMATE]["misses_universal"] == 1
