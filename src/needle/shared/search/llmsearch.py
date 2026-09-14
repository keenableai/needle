from needle.shared.search.base import SearchResult
from needle.shared.search.queryops import QueryOps

SYSTEM_PROMPT = (
    "Search the web for the user's query, then answer in one short paragraph. "
    "Cite every source you rely on."
)


def user_prompt(ops: QueryOps) -> str:
    parts = [ops.text]
    if ops.after:
        parts.append(f"Only use sources published after {ops.after.isoformat()}.")
    if ops.before:
        parts.append(f"Only use sources published before {ops.before.isoformat()}.")
    return " ".join(parts)


def cited_then_hits(
    cited: list[SearchResult], hits: list[SearchResult], num_results: int
) -> list[SearchResult]:
    seen = {r.url for r in cited}
    merged = list(cited)
    for hit in hits:
        if hit.url not in seen:
            seen.add(hit.url)
            merged.append(hit)
    return merged[:num_results]
