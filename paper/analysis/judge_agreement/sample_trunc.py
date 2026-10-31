import json
import random
import sys
from pathlib import Path

from needle.shared.judge import QueryProfile, build_judge_input, judge_instructions
from needle.shared.metrics import normalize_url

hf_dir, out_dir, n_queries, n_parts = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
CAP = int(sys.argv[5])
rng = random.Random(7)
out_dir.mkdir(parents=True, exist_ok=True)
runs = sorted(p for p in hf_dir.iterdir() if p.is_dir() and (p / "ndcg.json").exists() and len(list((p / "ndcg").glob("*.json"))) >= 15)
step = len(runs) / n_queries
chosen_runs = [runs[int(i * step + step / 2)] for i in range(n_queries)]

items, key, queries = [], {}, []
for qi, run in enumerate(chosen_runs):
    rep = json.load(open(run / "ndcg.json"))
    engines = {}
    for name, e in rep["engines"].items():
        p = run / e.get("per_query_path", "")
        if name == "ultimate" or not p.exists():
            continue
        engines[name] = {pq["query"]: pq for pq in json.load(open(p))["per_query"]}
    candidates = sorted(q for q in next(iter(engines.values())) if sum(
        1 for pqs in engines.values() if q in pqs and pqs[q]["search_error"] is None and not pqs[q]["judge_errors"]) >= 15)
    q = rng.choice(candidates)
    today = run.name[:10]
    profile_d = None
    uniq = {}
    membership = {}
    for name, pqs in engines.items():
        pq = pqs.get(q)
        if pq is None or pq["search_error"] is not None or pq["judge_errors"]:
            continue
        profile_d = profile_d or pq["query_profile"]
        positions = []
        for r in pq["results"]:
            k = (normalize_url(r["url"]), r["title"], r["snippet"])
            if k not in uniq:
                uniq[k] = {"id": len(items) + len(uniq), "url": r["url"], "title": r["title"], "snippet": r["snippet"], "gpt": r["rating"]}
            positions.append(uniq[k]["id"])
        membership[name] = {"positions": positions, "penalized": pq["penalized_ratings"], "ndcg": pq["ndcg"]}
    profile = QueryProfile(**{k: tuple(v) if isinstance(v, list) else v for k, v in profile_d.items()})
    for u in uniq.values():
        prompt = build_judge_input(q, url=u["url"], title=u["title"], content=(u["snippet"] or "")[:CAP], today=today, profile=profile)
        items.append({"id": u["id"], "q": qi, "prompt": prompt})
        key[u["id"]] = {"q": qi, "gpt": u["gpt"], "url": u["url"]}
    queries.append({"q": qi, "run": run.name, "query": q, "today": today, "profile": profile_d, "engines": membership})
    print(qi, run.name, repr(q), "unique", len(uniq), "engines", len(membership))

(out_dir / "system.txt").write_text(judge_instructions())
json.dump(queries, open(out_dir / "queries.json", "w"), indent=1)
json.dump(key, open(out_dir / "key.json", "w"), indent=1)
rng.shuffle(items)
per = -(-len(items) // n_parts)
for i in range(n_parts):
    part = sorted(items[i * per:(i + 1) * per], key=lambda x: (x["q"], x["id"]))
    json.dump(part, open(out_dir / f"items_part{i + 1}.json", "w"), indent=1)
    print("part", i + 1, len(part))
print("total items", len(items))
