import asyncio
from dataclasses import dataclass
from typing import Any

from keenbench.scholar.idconv import IdConverter
from keenbench.scholar.ids import PaperIds, extract_ids
from keenbench.scholar.models import AGE_BUCKETS
from keenbench.shared.recall import classify_misses, group_recall
from keenbench.shared.search import SearchClient, SearchResult, latency_stats


@dataclass(frozen=True)
class GoldPaper:
    text: str
    paper_key: str
    ids: dict[str, str]
    bucket: str
    suite: str
    age_bucket: str
    domain: str


def ids_match(gold: dict[str, str], found: PaperIds) -> bool:
    found_ids = found.as_match_dict()
    return any(found_ids.get(k) == v for k, v in gold.items())


def _grouped(scored: list[dict], field: str) -> dict[str, dict[str, Any]]:
    return group_recall(scored, lambda pq: pq[field])


def _age_order(groups: dict[str, dict]) -> dict[str, dict]:
    def rank(bucket: str) -> int:
        return AGE_BUCKETS.index(bucket) if bucket in AGE_BUCKETS else len(AGE_BUCKETS)

    return dict(sorted(groups.items(), key=lambda kv: rank(kv[0])))


async def run_papers(
    queries: list[GoldPaper],
    engines: dict[str, SearchClient],
    *,
    num_results: int = 5,
    snippet_chars: int = 500,
    idconv: IdConverter | None = None,
) -> dict[str, Any]:
    engine_names = list(engines)

    async def eval_engine(query: GoldPaper, results: list[SearchResult] | None, err: Any) -> dict:
        pq: dict[str, Any] = {
            "query": query.text,
            "paper_key": query.paper_key,
            "bucket": query.bucket,
            "suite": query.suite,
            "age_bucket": query.age_bucket,
            "domain": query.domain,
            "hit_rank": None,
            "n_results": 0,
            "results": [],
            "search_error": err,
        }
        if err is not None:
            return pq
        results = results or []
        pq["n_results"] = len(results)
        found = [extract_ids(r, snippet_chars=snippet_chars) for r in results]
        if idconv is not None and "pmid" in query.ids:
            need = [f.pmcid for f in found if f.pmcid and not f.pmid]
            if need:
                mapping = await idconv.pmc_to_pmid(need)
                for f in found:
                    if f.pmcid and not f.pmid:
                        f.pmid = mapping.get(f.pmcid)
        pq["results"] = [
            {"url": r.url, "title": r.title, "ids": f.as_match_dict()}
            for r, f in zip(results, found, strict=True)
        ]
        for rank, f in enumerate(found, start=1):
            if ids_match(query.ids, f):
                pq["hit_rank"] = rank
                break
        return pq

    async def run_query(query: GoldPaper) -> list[dict]:
        searches = await asyncio.gather(
            *[engines[n].search(query.text, num_results=num_results) for n in engine_names]
        )
        return await asyncio.gather(*[eval_engine(query, r, e) for r, e in searches])

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
            "by_bucket": _grouped(scored, "bucket"),
            "by_suite": _grouped(scored, "suite"),
            "by_age": _age_order(_grouped(scored, "age_bucket")),
            "by_domain": _grouped(scored, "domain"),
            "per_query": per_query,
        }

    classify_misses(query_outs, engine_names, engines_out)

    return {
        "num_queries": len(queries),
        "num_results": num_results,
        "snippet_chars": snippet_chars,
        "engines": engines_out,
    }
