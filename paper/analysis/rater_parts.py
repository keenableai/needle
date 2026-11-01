import json
import os
import random
import sys

from needle.shared.search import DEFAULT_SNIPPET_CHARS, SearchResult, capped_snippet

items_path, pages_path, out_dir, n_parts = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
items = json.load(open(items_path))
pages = json.load(open(pages_path))

views = []
for it in items:
    page = pages.get(str(it["id"]), {})
    views.append({
        "id": it["id"],
        "today": it["today"],
        "query": it["query"],
        "url": it["url"],
        "title": it["title"],
        "snippet": capped_snippet(SearchResult(url=it["url"], snippet=it["snippet"]), DEFAULT_SNIPPET_CHARS),
        "page_excerpt": (page.get("content") or "")[:3000],
    })

for rater, seed in (("A", 11), ("B", 22)):
    order = views[:]
    random.Random(seed).shuffle(order)
    d = os.path.join(out_dir, f"rater_{rater}")
    os.makedirs(d, exist_ok=True)
    size = -(-len(order) // n_parts)
    for i in range(n_parts):
        part = order[i * size:(i + 1) * size]
        json.dump(part, open(os.path.join(d, f"part{i + 1}.json"), "w"), indent=0)
    print(rater, "parts", n_parts, "size", size)
empty = sum(1 for v in views if not v["page_excerpt"])
print("items", len(views), "without page excerpt", empty)
