import json
import sys
from collections import defaultdict
from multiprocessing import Pool
from pathlib import Path

if __name__ == "__main__":
    src, hf_dir, history, out_history = sys.argv[1], Path(sys.argv[2]), sys.argv[3], sys.argv[4]
    sys.path.insert(0, src)
from needle.finance.canon import cached_squad_norm, parse_amount, phrase_in, squad_norm, text_amounts  # noqa: E402
from needle.finance.models import cues_for  # noqa: E402

K = 5
TIGHT = 0.001
_cache = {}


def text_of(r):
    return " ".join(p for p in (r.get("title"), (r.get("snippet") or "")[:2000]) if p)


def amount_match(value, aliases, text, tol, cues):
    key = (text, cues)
    if key not in _cache:
        norm = squad_norm(text)
        cue_ok = not cues or any(phrase_in(cached_squad_norm(c), norm) for c in cues)
        _cache[key] = (cue_ok, text_amounts(text, skip_year_like=True) if cue_ok else [])
    cue_ok, amounts = _cache[key]
    if not cue_ok:
        return False
    for form in [f for f in [value, *aliases] if f not in (None, "")]:
        gold = parse_amount(form)
        if gold is None:
            continue
        for amount in amounts:
            if gold == 0:
                if abs(amount) < 1:
                    return True
            elif abs(amount - gold) / abs(gold) <= tol:
                return True
    return False


def process(run):
    run = Path(run)
    gold = {}
    for line in open(run / "gold.jsonl"):
        if line.strip():
            g = json.loads(line)
            gold[g["query_text"]] = g["gold"]
    rep = json.load(open(run / "recall.json"))
    ts = run.name[:13] + ":" + run.name[13:15] + "Z"
    any_hit = defaultdict(bool)
    nq = rep["num_queries"]
    rows = []
    for eng, e in rep["engines"].items():
        p = run / e.get("per_query_path", "")
        if eng == "ultimate" or not p.exists():
            continue
        hits = errs = n = 0
        for pq in json.load(open(p))["per_query"]:
            n += 1
            if pq["search_error"] is not None:
                errs += 1
                continue
            g = gold.get(pq["query"])
            if g is None:
                continue
            if g["field_type"] == "money":
                aliases = tuple(str(a) for a in g["aliases"] or [])
                hit = any(amount_match(g["value"], aliases, text_of(r), TIGHT, cues_for(g["field"])) for r in pq["results"][:K])
            else:
                hit = pq["hit_rank"] is not None
            hits += hit
            any_hit[pq["query"]] |= hit
        lat = e.get("latency") or {}
        rows.append({"ts": ts, "bench": "finance", "engine": eng, "recall": hits / n if n else None, "num_scored": n,
                     "num_queries": n, "search_errors": errs, "p50_ms": lat.get("p50_ms"), "p95_ms": lat.get("p95_ms")})
    rows.append({"ts": ts, "bench": "finance", "engine": "ultimate", "recall": sum(any_hit.values()) / nq, "num_scored": nq,
                 "num_queries": nq, "search_errors": 0, "p50_ms": None, "p95_ms": None})
    return rows


if __name__ == "__main__":
    runs = sorted(str(p) for p in hf_dir.iterdir() if p.is_dir())
    with Pool(4) as pool:
        rows = [r for part in pool.map(process, runs) for r in part]
    strict_ts = {r["ts"] for r in rows}
    out = []
    replaced = 0
    for line in open(history):
        if not line.strip():
            continue
        r = json.loads(line)
        if r["bench"] == "finance" and r["ts"] in strict_ts:
            replaced += 1
            continue
        out.append(r)
    out.extend(rows)
    with open(out_history, "w") as f:
        for r in out:
            f.write(json.dumps(r) + "\n")
    json.dump(rows, open(out_history + ".strict_rows.json", "w"), indent=1)
    print("replaced", replaced, "finance rows with", len(rows), "strict rows")
