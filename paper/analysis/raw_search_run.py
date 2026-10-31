import asyncio
import json
import sys
from dataclasses import asdict

from dotenv import load_dotenv

load_dotenv("/home/yallen/needle/.env")

from needle.shared.cli import aclose_all, build_clients_or_exit  # noqa: E402
from needle.shared.search import DEFAULT_SNIPPET_CHARS  # noqa: E402
from needle.shared.search.base import search_all  # noqa: E402

queries_path, out, engines = sys.argv[1], sys.argv[2], sys.argv[3]
texts = [json.loads(l)["query_text"] for l in open(queries_path) if l.strip()]
clients = build_clients_or_exit(engines, snippet_chars=DEFAULT_SNIPPET_CHARS)
for name, k in (("chatgpt-search", 4), ("claude-search", 2), ("jina", 2)):
    if name in clients:
        clients[name].set_max_concurrency(k)
print("queries", len(texts), "engines", list(clients), flush=True)


async def go():
    try:
        return await search_all(clients, texts, num_results=5, concurrent_search=True)
    finally:
        await aclose_all(*clients.values())


runs = asyncio.run(go())
dump = {"num_results": 5, "snippet_chars": DEFAULT_SNIPPET_CHARS, "engines": list(clients), "queries": []}
for text, searches in zip(texts, runs, strict=True):
    row = {"query": text, "by_engine": {}}
    for name, s in zip(clients, searches, strict=True):
        row["by_engine"][name] = {"queried_at": s.queried_at, "error": s.error, "results": [asdict(r) for r in (s.results or [])]}
    dump["queries"].append(row)
json.dump(dump, open(out, "w"))
errs = {name: sum(1 for q in dump["queries"] if q["by_engine"][name]["error"] is not None) for name in clients}
print("done; errors", errs)
