from dataclasses import dataclass
from typing import Any

from keenbench.scholar.idconv import IdConverter
from keenbench.scholar.ids import PaperIds, extract_ids
from keenbench.shared.recall import (
    build_match_rows,
    first_rank,
    group_recall,
    recall_summary,
    run_known_item_eval,
)
from keenbench.shared.search import DEFAULT_SNIPPET_CHARS, SearchClient, SearchResult


@dataclass(frozen=True)
class GoldPaper:
    text: str
    paper_key: str
    ids: dict[str, str]
    bucket: str


def ids_match(gold: dict[str, str], found: PaperIds) -> bool:
    found_ids = found.as_match_dict()
    return any(found_ids.get(k) == v for k, v in gold.items())


def _summary(per_query: list[dict], latency: dict | None) -> dict[str, Any]:
    scored = [pq for pq in per_query if pq["search_error"] is None]
    return {
        **recall_summary(per_query, scored, latency),
        "by_bucket": group_recall(scored, lambda pq: pq["bucket"]),
    }


async def run_papers(
    queries: list[GoldPaper],
    engines: dict[str, SearchClient],
    *,
    num_results: int = 5,
    snippet_chars: int = DEFAULT_SNIPPET_CHARS,
    idconv: IdConverter | None = None,
) -> dict[str, Any]:
    async def eval_engine(query: GoldPaper, results: list[SearchResult] | None, err: Any) -> dict:
        pq: dict[str, Any] = {
            "query": query.text,
            "paper_key": query.paper_key,
            "bucket": query.bucket,
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
        matches = [ids_match(query.ids, f) for f in found]
        pq["results"] = build_match_rows(results, found, matches, snippet_chars=snippet_chars)
        pq["hit_rank"] = first_rank(matches)
        return pq

    return await run_known_item_eval(
        queries,
        engines,
        eval_engine,
        _summary,
        num_results=num_results,
        snippet_chars=snippet_chars,
    )
