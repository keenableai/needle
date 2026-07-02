import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from keenbench.scholar.idconv import IdConverter
from keenbench.scholar.ids import PaperIds, extract_ids
from keenbench.scholar.models import AGE_BUCKETS
from keenbench.shared.search import SearchClient, SearchResult


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


def _group(scored: list[dict], key: Callable[[dict], str]) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict]] = {}
    for pq in scored:
        groups.setdefault(key(pq), []).append(pq)
    out = {}
    for name, pqs in groups.items():
        hits = [pq for pq in pqs if pq["hit_rank"] is not None]
        out[name] = {"n": len(pqs), "recall_at_k": len(hits) / len(pqs)}
    return out


def _age_order(groups: dict[str, dict]) -> dict[str, dict]:
    def rank(bucket: str) -> int:
        return AGE_BUCKETS.index(bucket) if bucket in AGE_BUCKETS else len(AGE_BUCKETS)

    return dict(sorted(groups.items(), key=lambda kv: rank(kv[0])))


def _shallow_index(scored: list[dict]) -> dict[str, Any]:
    by_paper: dict[str, dict[str, bool]] = {}
    for pq in scored:
        by_paper.setdefault(pq["paper_key"], {})[pq["bucket"]] = pq["hit_rank"] is not None
    paired = {k: v for k, v in by_paper.items() if "title" in v and "body" in v}
    title_hit = [v for v in paired.values() if v["title"]]
    shallow = [v for v in title_hit if not v["body"]]
    return {
        "paired_papers": len(paired),
        "title_hit_papers": len(title_hit),
        "shallow_papers": len(shallow),
        "shallow_index_rate": (len(shallow) / len(title_hit)) if title_hit else None,
    }


async def run_papers(
    queries: list[GoldPaper],
    engines: dict[str, SearchClient],
    *,
    num_results: int = 5,
    snippet_chars: int = 500,
    idconv: IdConverter | None = None,
) -> dict[str, Any]:
    engine_names = list(engines)

    async def eval_engine(
        query: GoldPaper, results: list[SearchResult] | None, err: Any
    ) -> dict:
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
            "by_bucket": dict(sorted(_group(scored, lambda pq: pq["bucket"]).items())),
            "by_suite": dict(sorted(_group(scored, lambda pq: pq["suite"]).items())),
            "by_age": _age_order(_group(scored, lambda pq: pq["age_bucket"])),
            "by_domain": dict(sorted(_group(scored, lambda pq: pq["domain"]).items())),
            "shallow_index": _shallow_index(scored),
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
