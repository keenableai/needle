import json
import re
import sys
from collections import defaultdict
from pathlib import Path

src, hf_dir, table_tex = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
sys.path.insert(0, src)
from needle.finance.canon import cached_squad_norm, parse_amount, phrase_in, squad_norm, text_amounts  # noqa: E402
from needle.finance.models import cues_for  # noqa: E402

NAMES = {
    "keenable": "Keenable", "exa": "Exa", "brave-llmcontext": "Brave (LLM ctx)", "perplexity": "Perplexity",
    "parallel": "Parallel", "brave": "Brave", "you": "You.com", "linkup": "Linkup", "deepseek": "DeepSeek",
    "context": "Context", "kagi": "Kagi", "firecrawl": "Firecrawl", "chatgpt-search": "ChatGPT search",
    "google": "Google (Serper)", "octen": "Octen", "bing": "Bing (SearchAPI)", "claude-search": "Claude search",
    "jina": "Jina", "tavily": "Tavily", "tinyfish": "TinyFish", "ceramic": "Ceramic",
}
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


gold = {}
runs = sorted(p for p in hf_dir.iterdir() if p.is_dir())
for run in runs:
    for line in open(run / "gold.jsonl"):
        if line.strip():
            g = json.loads(line)
            gold[g["query_text"]] = g["gold"]

cur = defaultdict(lambda: [0, 0])
strict = defaultdict(lambda: [0, 0])
ceil_cur = defaultdict(bool)
ceil_strict = defaultdict(bool)
for run in runs:
    for eng in NAMES:
        p = run / "recall" / f"{eng}.json"
        if not p.exists():
            continue
        for pq in json.load(open(p))["per_query"]:
            if pq["search_error"] is not None:
                continue
            g = gold.get(pq["query"])
            if g is None:
                continue
            qk = (run.name, pq["query"])
            hit_cur = pq["hit_rank"] is not None
            if g["field_type"] == "money":
                aliases = tuple(str(a) for a in g["aliases"] or [])
                hit_strict = any(amount_match(g["value"], aliases, text_of(r), TIGHT, cues_for(g["field"])) for r in pq["results"][:K])
            else:
                hit_strict = hit_cur
            cur[eng][0] += hit_cur; cur[eng][1] += 1
            strict[eng][0] += hit_strict; strict[eng][1] += 1
            ceil_cur[qk] |= hit_cur
            ceil_strict[qk] |= hit_strict

cc = sum(ceil_cur.values()) / len(ceil_cur)
cs = sum(ceil_strict.values()) / len(ceil_strict)
print("ceiling current %.3f strict %.3f" % (cc, cs))
rows = []
for line in open(table_tex):
    cells = [c.strip() for c in line.split("&")]
    if len(cells) < 8 or "ceilbar" in line:
        continue
    name = re.sub(r"\$.*", "", cells[0]).strip()
    m = re.search(r"\\sharebar\{([\d.]+)\}", cells[1])
    rows.append((name, float(m.group(1))))
overall = dict(rows)
inv = {v: k for k, v in NAMES.items()}
out = []
for name, share in rows:
    e = inv[name]
    rc = cur[e][0] / cur[e][1]
    rs = strict[e][0] / strict[e][1]
    d_fin_share = rs / cs - rc / cc
    new_overall = share + 100 * d_fin_share / 5
    out.append((name, rc, rs, rc / cc, rs / cs, share, new_overall))
    print(f"{name:18s} fin {rc:.3f}->{rs:.3f}  share {rc/cc:.3f}->{rs/cs:.3f}  overall {share:.1f}->{new_overall:.1f}")


def tau_b(a, b):
    n = len(a); c = d = ta = tb = 0
    for i in range(n):
        for j in range(i + 1, n):
            x, y = a[i] - a[j], b[i] - b[j]
            if x == 0 and y == 0:
                continue
            if x == 0:
                ta += 1
            elif y == 0:
                tb += 1
            elif x * y > 0:
                c += 1
            else:
                d += 1
    return (c - d) / (((c + d + ta) * (c + d + tb)) ** 0.5)


print("finance column tau_b", round(tau_b([o[1] for o in out], [o[2] for o in out]), 3), "max |d fin share|", round(max(abs(o[4] - o[3]) for o in out), 3), "mean", round(sum(o[4] - o[3] for o in out) / len(out), 3))
print("overall tau_b", round(tau_b([o[5] for o in out], [o[6] for o in out]), 3), "max |d overall|", round(max(abs(o[6] - o[5]) for o in out), 2))
rank0 = sorted(out, key=lambda o: -o[5]); rank1 = sorted(out, key=lambda o: -o[6])
moves = {o[0]: rank1.index(o) - rank0.index(o) for o in out if rank1.index(o) != rank0.index(o)}
print("overall rank moves", moves)
