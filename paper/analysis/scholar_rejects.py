import collections
import json
import os
import sys
from unittest.mock import patch

from dotenv import load_dotenv

from needle.scholar import cli, generate
from needle.shared.llm import resolve_llm_model

load_dotenv()
out_path = sys.argv[1]
per_cell = int(sys.argv[2]) if len(sys.argv) > 2 else 10


def recording(original, sink):
    async def wrapper(*args, **kwargs):
        result = await original(*args, **kwargs)
        sink.append(result)
        return result

    return wrapper


def rate(c):
    return round(c["accepted"] / c["candidates"], 4)


gathered, generated = [], []
with (
    patch.object(generate, "bounded_gather", side_effect=recording(generate.bounded_gather, gathered)) as gather,
    patch.object(cli, "run_generate", side_effect=recording(cli.run_generate, generated)) as run,
):
    cli.Scholar().generate(out=os.devnull, per_cell=per_cell)

cells = [cell for cell, _ in gather.call_args_list[0].args[0]]
per = {c: collections.Counter() for c in cells}
for cand, _, drop in gathered[-1]:
    counts = per[cand.cell]
    counts["candidates"] += 1
    if drop is None:
        counts["accepted"] += 1
    else:
        counts["rejected"] += 1
        counts[f"first:{drop[0] if isinstance(drop, tuple) else drop}"] += 1
domains = collections.defaultdict(collections.Counter)
total = collections.Counter()
for (d, _), c in per.items():
    domains[d].update(c)
    total.update(c)
total["generic_title"] = generated[0][1].generic_title
summary = {d: {"candidates": c["candidates"], "accepted": c["accepted"], "pass_rate": rate(c)} for d, c in domains.items()}
args = run.call_args.kwargs
out = {
    "hour": args["hour_ts"].isoformat(), "seed": args["seed"], "per_cell": args["per_cell"], "model": resolve_llm_model(None),
    "cells": {f"{d}|{a}": dict(per[(d, a)]) for d, a in cells}, "domains": summary,
    "total": {**total, "pass_rate": rate(total)},
}
print("hour", out["hour"], "seed", out["seed"], "model", out["model"])
print("total", out["total"])
for d, v in summary.items():
    print(f"{d:20s} accepted {v['accepted']:3d} of {v['candidates']:3d} pass_rate {v['pass_rate']:.4f}")
json.dump(out, open(out_path, "w"), indent=1, sort_keys=True)
