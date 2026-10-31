import pytest

from needle.shared.recall import account_side, recall_summary, ultimate_per_query


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
    ],
)
def test_account_side_failures(error):
    assert account_side(error)


@pytest.mark.parametrize(
    "error",
    [
        _http(
            '429: {"error":{"code":"RATE_LIMIT_EXCEEDED","message":"Rate limit exceeded. Request a'
            ' higher limit at https://agent.tinyfish.ai/wallet"}}'
        ),
        _http('400: {"error":{"message":"Output blocked by content filtering policy"}}'),
        _http('400: {"message":"invalid domain","key_metadata":{"credits_remaining":991}}'),
        _http('422: {"message":"No search results available for query billing error resolution"}'),
        _http("503: Our servers are currently overloaded"),
        _http("500: Internal Server Error"),
        _http("429"),
        {"error_type": "transport", "error_message": "ReadTimeout"},
        {"error_type": "api_error", "error_message": "max_uses_exceeded"},
        {"error_type": "api_error", "error_message": "Bing didn't return any results."},
        {"error_type": "bad_json", "error_message": "Expecting value"},
        {"error_type": "all_engines_failed", "error_message": "every engine errored"},
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
    assert summary["search_errors"] == 2
    assert summary["account_errors"] == 1
    assert summary["service_errors"] == 1
    assert [pq["score"] for pq in per_query] == [1.0, 0.0, None]


def test_ultimate_counts_query_when_any_failure_is_service_side():
    entries = [_pq(error=_http("401: no")), _pq(error=_http("429: slow down"))]
    out = ultimate_per_query([entries], cap=5)
    assert out[0]["search_error"] == _http("429: slow down")
    assert recall_summary(out, None)["num_scored"] == 1
    both_account = ultimate_per_query([[_pq(error=_http("401: no"))] * 2], cap=5)
    assert recall_summary(both_account, None)["num_scored"] == 0
