import json
import random
import sys
from collections import defaultdict
from pathlib import Path

fin_dir, leg_dir = Path(sys.argv[1]), Path(sys.argv[2])
rng = random.Random(3)


def collect(hf_dir, report, qfile, key_of):
    obs = defaultdict(lambda: defaultdict(dict))
    for run in sorted(p for p in hf_dir.iterdir() if p.is_dir() and (p / report).exists()):
        meta = {}
        for line in open(run / qfile):
            if line.strip():
                g = json.loads(line)
                k = key_of(g)
                if k:
                    meta[g["query_text"]] = k
        rep = json.load(open(run / report))
        for eng, e in rep["engines"].items():
            p = run / e.get("per_query_path", "")
            if eng == "ultimate" or not p.exists():
                continue
            for pq in json.load(open(p))["per_query"]:
                m = meta.get(pq["query"])
                if m is None or pq.get("search_error") is not None:
                    continue
                target, syntax = m
                obs[target][syntax][(run.name, eng)] = pq.get("hit_rank") is not None
    return obs


def legal_key(g):
    o = json.loads(g["query_origin"])
    gold = json.loads(g["gold"])
    return (o["bucket"] + ":" + gold["case_key"], o.get("syntax", "plain"))


def fin_key(g):
    o = json.loads(g["query_origin"])
    if g["gold"]["field"] != "filing":
        return None
    return ("filing:" + str(g["gold"]["value"]), o.get("syntax", "plain"))


def paired(obs, label):
    for variant in ("quoted", "site", "date"):
        diffs = []
        targets = 0
        for target, by_syn in obs.items():
            if "plain" not in by_syn or variant not in by_syn:
                continue
            engines = {e for _, e in by_syn["plain"]} & {e for _, e in by_syn[variant]}
            if not engines:
                continue
            targets += 1
            for e in engines:
                p = [h for (r, ee), h in by_syn["plain"].items() if ee == e]
                v = [h for (r, ee), h in by_syn[variant].items() if ee == e]
                diffs.append(sum(v) / len(v) - sum(p) / len(p))
        if not diffs:
            print(f"{label} {variant}: no paired targets")
            continue
        mean = sum(diffs) / len(diffs)
        boots = []
        by_t = defaultdict(list)
        for i, d in enumerate(diffs):
            by_t[i // max(1, len(diffs) // targets)].append(d)
        groups = list(by_t.values())
        for _ in range(2000):
            sample = [d for _ in groups for d in groups[rng.randrange(len(groups))]]
            boots.append(sum(sample) / len(sample))
        boots.sort()
        print(f"{label} {variant}: paired targets {targets}, engine-pairs {len(diffs)}, mean recall change {mean:+.3f} (95% CI {boots[int(0.025*len(boots))]:+.3f}..{boots[int(0.975*len(boots))]:+.3f})")


leg = collect(leg_dir, "legal.json", "legal.jsonl", legal_key)
case = {k: v for k, v in leg.items() if k.startswith("caselaw:")}
code = {k: v for k, v in leg.items() if k.startswith("code:")}
print("caselaw targets", len(case), "with >1 syntax", sum(1 for v in case.values() if len(v) > 1))
print("code targets", len(code), "with >1 syntax", sum(1 for v in code.values() if len(v) > 1))
paired(case, "caselaw")
paired(code, "code")
fin = collect(fin_dir, "recall.json", "gold.jsonl", fin_key)
print("filing targets", len(fin), "with >1 syntax", sum(1 for v in fin.values() if len(v) > 1))
paired(fin, "filing")
