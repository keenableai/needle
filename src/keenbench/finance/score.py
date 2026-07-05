import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from keenbench.companyfill.canon import gold_in_text
from keenbench.finance.models import QUARTERLY_FIELDS
from keenbench.shared.search import SearchClient, SearchResult, latency_stats

ADSH_RE = re.compile(r"\b(\d{10})-?(\d{2})-?(\d{6})\b")


def norm_adsh(raw: str) -> str:
    return raw.replace("-", "")


def extract_adshes(result: SearchResult, *, snippet_chars: int) -> set[str]:
    text = f"{result.url or ''} {_capped(result, snippet_chars)}"
    return {"".join(m.groups()) for m in ADSH_RE.finditer(text)}


def _capped(result: SearchResult, snippet_chars: int) -> str:
    snippet = result.snippet or ""
    if snippet_chars > 0:
        snippet = snippet[:snippet_chars]
    return " ".join(part for part in (result.title, snippet) if part)


@dataclass(frozen=True)
class GoldFinance:
    text: str
    kind: str
    bucket: str
    syntax: str
    field: str = ""
    field_type: str = ""
    value: Any = None
    aliases: tuple[str, ...] = ()
    age_bucket: str = ""
    adsh: str = ""
    form: str = ""
    tier: str = ""


def answer_rank(
    query: GoldFinance, results: list[SearchResult], *, snippet_chars: int
) -> int | None:
    cues = QUARTERLY_FIELDS[query.field].cues if query.field in QUARTERLY_FIELDS else ()
    for rank, result in enumerate(results, start=1):
        text = _capped(result, snippet_chars)
        if gold_in_text(
            query.field_type,
            query.value,
            query.aliases,
            text=text,
            url=result.url,
            cues=cues,
        ):
            return rank
    return None


def item_rank(query: GoldFinance, results: list[SearchResult], *, snippet_chars: int) -> int | None:
    gold = norm_adsh(query.adsh)
    for rank, result in enumerate(results, start=1):
        if gold in extract_adshes(result, snippet_chars=snippet_chars):
            return rank
    return None


def _group(scored: list[dict], key: Callable[[dict], str]) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict]] = {}
    for pq in scored:
        groups.setdefault(key(pq), []).append(pq)
    out = {}
    for name, pqs in sorted(groups.items()):
        hits = [pq for pq in pqs if pq["hit_rank"] is not None]
        out[name] = {"n": len(pqs), "recall_at_k": len(hits) / len(pqs)}
    return out


async def run_finance(
    queries: list[GoldFinance],
    engines: dict[str, SearchClient],
    *,
    num_results: int = 5,
    snippet_chars: int = 500,
) -> dict[str, Any]:
    engine_names = list(engines)

    def eval_engine(query: GoldFinance, results: list[SearchResult] | None, err: Any) -> dict:
        pq: dict[str, Any] = {
            "query": query.text,
            "bucket": query.bucket,
            "syntax": query.syntax,
            "field": query.field,
            "value": query.value,
            "tier": query.tier,
            "hit_rank": None,
            "n_results": 0,
            "results": [],
            "search_error": err,
        }
        if err is not None:
            return pq
        results = results or []
        pq["n_results"] = len(results)
        pq["results"] = [
            {"url": r.url, "title": r.title, "snippet": _capped(r, snippet_chars)} for r in results
        ]
        if query.kind == "item":
            pq["hit_rank"] = item_rank(query, results, snippet_chars=snippet_chars)
        else:
            pq["hit_rank"] = answer_rank(query, results, snippet_chars=snippet_chars)
        return pq

    async def run_query(query: GoldFinance) -> list[dict]:
        searches = await asyncio.gather(
            *[engines[n].search(query.text, num_results=num_results) for n in engine_names]
        )
        return [eval_engine(query, r, e) for r, e in searches]

    query_outs = await asyncio.gather(*[run_query(q) for q in queries])

    engines_out: dict[str, dict[str, Any]] = {}
    for idx, name in enumerate(engine_names):
        per_query = [entries[idx] for entries in query_outs]
        scored = [pq for pq in per_query if pq["search_error"] is None]
        hits = [pq for pq in scored if pq["hit_rank"] is not None]
        engines_out[name] = {
            "recall_at_k": len(hits) / len(scored) if scored else 0.0,
            "mrr_at_k": (sum(1.0 / pq["hit_rank"] for pq in hits) / len(scored) if scored else 0.0),
            "num_scored": len(scored),
            "search_errors": sum(1 for pq in per_query if pq["search_error"] is not None),
            "latency": latency_stats(engines[name].latencies_ms),
            "by_bucket": _group(scored, lambda pq: pq["bucket"]),
            "by_syntax": _group(scored, lambda pq: pq["syntax"]),
            "by_field": _group([pq for pq in scored if pq["field"]], lambda pq: pq["field"]),
            "by_tier": _group([pq for pq in scored if pq["tier"]], lambda pq: pq["tier"]),
            "per_query": per_query,
        }

    _classify_misses(query_outs, engine_names, engines_out)

    return {
        "num_queries": len(queries),
        "num_results": num_results,
        "snippet_chars": snippet_chars,
        "engines": engines_out,
    }


def _classify_misses(
    query_outs: list[list[dict]],
    engine_names: list[str],
    engines_out: dict[str, dict[str, Any]],
) -> None:
    any_hit = [any(pq["hit_rank"] is not None for pq in entries) for entries in query_outs]
    for idx, name in enumerate(engine_names):
        system_specific = universal = 0
        for entries, others_found in zip(query_outs, any_hit, strict=True):
            pq = entries[idx]
            if pq["search_error"] is not None or pq["hit_rank"] is not None:
                continue
            if pq["n_results"] == 0:
                continue
            if others_found:
                system_specific += 1
            else:
                universal += 1
        engines_out[name]["misses_system_specific"] = system_specific
        engines_out[name]["misses_universal"] = universal
