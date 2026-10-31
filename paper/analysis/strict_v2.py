import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from needle.finance.canon import cached_squad_norm, parse_amount, phrase_in, squad_norm, text_amounts
from needle.finance.models import cues_for

K = 5
TIGHT = 0.001
SITE_RE = re.compile(r"site:(\S+)")


def host_ok(url, site):
    from urllib.parse import urlsplit
    h = (urlsplit(url).hostname or "").lower()
    return h == site or h.endswith("." + site)


NUM_RE = re.compile(r"(?<![\w.])(\()?\s*\$?\s*(-)?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s*(\))?(?![\w.])(?!\s*(?:%|percent\b|per cent\b|x\b|times\b))")
_cache = {}
_tcache = {}


def text_of(r):
    return " ".join(p for p in (r.get("title"), (r.get("snippet") or "")[:2000]) if p)


def cue_amounts(text, cues):
    key = (text, cues)
    if key not in _cache:
        norm = squad_norm(text)
        cue_ok = not cues or any(phrase_in(cached_squad_norm(c), norm) for c in cues)
        _cache[key] = (cue_ok, text_amounts(text, skip_year_like=True) if cue_ok else [])
    return _cache[key]


def table_numbers(text):
    if text not in _tcache:
        out = []
        for m in NUM_RE.finditer(text):
            raw = m.group(3).replace(",", "") + (m.group(4) or "")
            try:
                v = float(raw)
            except ValueError:
                continue
            neg = bool(m.group(1) and m.group(5)) or bool(m.group(2))
            year_like = "," not in m.group(3) and not m.group(4) and 1900 <= v <= 2100
            out.append((-v if neg else v, year_like))
        _tcache[text] = out
    return _tcache[text]


def close(a, gold):
    return gold != 0 and abs(a - gold) / abs(gold) <= TIGHT


def match_v1(value, aliases, text, cues):
    cue_ok, amounts = cue_amounts(text, cues)
    if not cue_ok:
        return False
    for form in [f for f in [value, *aliases] if f not in (None, "")]:
        gold = parse_amount(form)
        if gold is None:
            continue
        for a in amounts:
            if gold == 0:
                if abs(a) < 1:
                    return True
            elif close(a, gold):
                return True
    return False


def match_v2(value, aliases, text, cues):
    if match_v1(value, aliases, text, cues):
        return True, False
    cue_ok, _ = cue_amounts(text, cues)
    if not cue_ok:
        return False, False
    gold = parse_amount(value)
    if gold is None or gold == 0:
        return False, False
    for n, year_like in table_numbers(text):
        if abs(n) < 1:
            continue
        for scale in (1.0, 1e3, 1e6):
            if scale > 1 and (abs(n) >= 1e6 or year_like):
                continue
            if close(n * scale, gold):
                return True, True
    return False, False


def process(run):
    run = Path(run)
    gold = {}
    for line in open(run / "gold.jsonl"):
        if line.strip():
            g = json.loads(line)
            gold[g["query_text"]] = g
    rep = json.load(open(run / "recall.json"))
    ts = run.name[:13] + ":" + run.name[13:15] + "Z"
    any_hit = defaultdict(bool)
    nq = rep["num_queries"]
    rows = []
    new_hits = []
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
            gg = g["gold"]
            site = SITE_RE.search(pq["query"])
            site = site.group(1).lower().strip('"') if site else None
            if gg["field_type"] == "money":
                aliases = tuple(str(a) for a in gg["aliases"] or [])
                hit = False
                for i, r in enumerate(pq["results"][:K]):
                    ok, is_new = match_v2(gg["value"], aliases, text_of(r), cues_for(gg["field"]))
                    if ok and site and not host_ok(r["url"], site):
                        ok = False
                    if ok:
                        hit = True
                        if is_new:
                            prov = json.loads(g["query_origin"]).get("provenance", {})
                            new_hits.append({"run": run.name, "engine": eng, "query": pq["query"], "company": prov.get("entity"),
                                             "field": gg["field"], "gold_value": gg["value"], "rank": i + 1,
                                             "title": r.get("title"), "url": r["url"], "snippet": (r.get("snippet") or "")[:1500]})
                        break
            else:
                hit = pq["hit_rank"] is not None
                if hit and site and not host_ok(pq["results"][pq["hit_rank"] - 1]["url"], site):
                    hit = False
            hits += hit
            any_hit[pq["query"]] |= hit
        lat = e.get("latency") or {}
        rows.append({"ts": ts, "bench": "finance", "engine": eng, "recall": hits / n if n else None, "num_scored": n,
                     "num_queries": n, "search_errors": errs, "p50_ms": lat.get("p50_ms"), "p95_ms": lat.get("p95_ms")})
    rows.append({"ts": ts, "bench": "finance", "engine": "ultimate", "recall": sum(any_hit.values()) / nq, "num_scored": nq,
                 "num_queries": nq, "search_errors": 0, "p50_ms": None, "p95_ms": None})
    return rows, new_hits


if __name__ == "__main__":
    import importlib
    src, hf_dir, shard, nshards, out_json = sys.argv[1], Path(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
    runs = sorted(str(p) for p in hf_dir.iterdir() if p.is_dir())[shard::nshards]
    rows, new = [], []
    for r in runs:
        rr, nn = process(r)
        rows.extend(rr)
        new.extend(nn)
        print(r, "done", "new hits so far", len(new), flush=True)
    json.dump({"rows": rows, "new_hits": new}, open(out_json, "w"))
    print("shard", shard, "rows", len(rows), "new hits", len(new))
