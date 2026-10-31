import collections
import glob
import json
import os
import random
import re
import sys
from datetime import date, timedelta

site, out_dir, per_bucket = sys.argv[1], sys.argv[2], int(sys.argv[3])
rng = random.Random(2026)
os.makedirs(out_dir, exist_ok=True)

COURT_PHRASES = {
    "scotus": "supreme court", "ca1": "first circuit", "ca2": "second circuit", "ca3": "third circuit",
    "ca4": "fourth circuit", "ca5": "fifth circuit", "ca6": "sixth circuit", "ca7": "seventh circuit",
    "ca8": "eighth circuit", "ca9": "ninth circuit", "ca10": "tenth circuit", "ca11": "eleventh circuit",
    "cadc": "dc circuit", "cafc": "federal circuit",
}
OP_RE = re.compile(r"\b(site|after|before):\S+")


def plain_of(text):
    return " ".join(OP_RE.sub(" ", text).replace('"', " ").split())


def date_ops(filed):
    d = date.fromisoformat(filed)
    return f"after:{(d - timedelta(days=45)).isoformat()} before:{(d + timedelta(days=45)).isoformat()}"


def load_jsonl(pattern):
    for p in sorted(glob.glob(pattern)):
        for line in open(p):
            if line.strip():
                yield json.loads(line)


def as_obj(v):
    return json.loads(v) if isinstance(v, str) else v


legal = collections.defaultdict(dict)
for g in load_jsonl(os.path.join(site, "hflegal", "*", "legal.jsonl")):
    o, gold = as_obj(g["query_origin"]), as_obj(g["gold"])
    key = (o["bucket"], gold["case_key"])
    legal[key].setdefault("rows", {})[o.get("syntax", "plain")] = g
    legal[key]["gold"], legal[key]["origin"] = gold, o

fin = collections.defaultdict(dict)
for g in load_jsonl(os.path.join(site, "hf", "*", "gold.jsonl")):
    o = as_obj(g["query_origin"])
    if o["bucket"] != "filingdoc":
        continue
    key = g["gold"]["value"]
    fin[key].setdefault("rows", {})[o.get("syntax", "plain")] = g
    fin[key]["gold"], fin[key]["origin"] = g["gold"], o


def emit(rows_out, base_row, origin, gold, text, syntax, target):
    o = dict(origin)
    o["syntax"] = syntax
    o["paired_target"] = target
    r = dict(base_row)
    r["query_text"] = text
    r["query_origin"] = json.dumps(o)
    r["gold"] = gold if isinstance(base_row["gold"], dict) else json.dumps(gold)
    r["query_id"] = f"{target}:{syntax}"
    rows_out.append(r)


legal_out = []
case_keys = sorted(k for k in legal if k[0] == "caselaw" and legal[k]["gold"].get("court") in COURT_PHRASES)
rng.shuffle(case_keys)
for key in case_keys[:per_bucket]:
    t = legal[key]
    anyrow = next(iter(t["rows"].values()))
    plain = plain_of(anyrow["query_text"])
    phrase = COURT_PHRASES[t["gold"]["court"]]
    caption = plain[: -len(phrase)].strip() if plain.endswith(phrase) else plain
    variants = {
        "plain": plain,
        "quoted": f'"{caption}" {phrase}',
        "site": f"{plain} site:courtlistener.com",
        "date": f"{plain} {date_ops(t['gold']['date_filed'])}",
    }
    for syn, text in variants.items():
        emit(legal_out, anyrow, t["origin"], t["gold"], text, syn, f"caselaw:{key[1]}")

code_keys = sorted(k for k in legal if k[0] == "code" and "quoted" in legal[k]["rows"])
rng.shuffle(code_keys)
for key in code_keys[:per_bucket]:
    t = legal[key]
    quoted = t["rows"]["quoted"]["query_text"]
    plain = plain_of(quoted)
    variants = {"plain": plain, "quoted": quoted, "site": f"{plain} site:law.cornell.edu"}
    for syn, text in variants.items():
        emit(legal_out, t["rows"]["quoted"], t["origin"], t["gold"], text, syn, f"code:{key[1]}")

fin_out = []
fin_keys = sorted(k for k in fin if "quoted" in fin[k]["rows"])
rng.shuffle(fin_keys)
for key in fin_keys[:per_bucket]:
    t = fin[key]
    quoted = t["rows"]["quoted"]["query_text"]
    plain = plain_of(quoted)
    filed = t["origin"]["provenance"]["filed"]
    variants = {
        "plain": plain,
        "quoted": quoted,
        "site": f"{plain} site:sec.gov",
        "date": f"{plain} {date_ops(filed)}",
    }
    for syn, text in variants.items():
        emit(fin_out, t["rows"]["quoted"], t["origin"], t["gold"], text, syn, f"filing:{key}")

for name, rows in (("paired_legal.jsonl", legal_out), ("paired_finance.jsonl", fin_out)):
    with open(os.path.join(out_dir, name), "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(name, "rows", len(rows))
print("caselaw targets", min(per_bucket, len(case_keys)), "code", min(per_bucket, len(code_keys)), "filing", min(per_bucket, len(fin_keys)))
print("sample:", legal_out[0]["query_text"], "|", legal_out[1]["query_text"], "|", legal_out[3]["query_text"])
print("sample fin:", fin_out[0]["query_text"], "|", fin_out[1]["query_text"], "|", fin_out[3]["query_text"])
