import json
import re
import sys

R = sys.argv[1]
items = json.load(open(f"{R}/items_key.json"))
pages = json.load(open(f"{R}/pages.json"))


def spans(q):
    return [s.lower() for s in re.findall(r'"([^"]+)"', q) if s.strip()]


tot = snip_has = page_has = page_only = no_page = 0
by_bench = {}
for it in items:
    sp = spans(it["query"])
    if not sp:
        continue
    text = ((it.get("title") or "") + " " + (it.get("snippet") or "")).lower()
    page = (pages.get(str(it["id"]), {}).get("content") or "").lower()
    in_snip = all(s in text for s in sp)
    tot += 1
    if not page:
        no_page += 1
        continue
    in_page = all(s in text + " " + page for s in sp)
    snip_has += in_snip
    page_has += in_page
    page_only += (in_page and not in_snip)
print(f"items with quoted spans {tot}; with page text {tot - no_page}; span in title/snippet {snip_has}; in page or snippet {page_has}; rescued by page only {page_only} ({100*page_only/max(1,tot-no_page):.0f}% of fetched; {100*page_only/max(1,(tot-no_page)-snip_has):.0f}% of those missing from the snippet)")
