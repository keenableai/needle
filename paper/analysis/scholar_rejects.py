import asyncio
import collections
import json
import sys
from dataclasses import replace

from dotenv import load_dotenv

load_dotenv("/home/yallen/needle/.env")

from needle.scholar.generate import (  # noqa: E402
    ARXIV_DOMAINS,
    HEALTH_DOMAIN,
    OVERSAMPLE,
    GenStats,
    _bucket_query,
    _cell_candidates,
    _fetch_body,
    _subwindow_count,
    _subwindows,
    body_has_bad_anchor,
    degrade_title,
    query_ok,
    title_is_specific,
)
from needle.scholar.projection import LLM_BUCKETS  # noqa: E402
from needle.scholar.sources import ArxivClient, EuropePmcClient  # noqa: E402
from needle.shared.cli import aclose_all, current_hour, require_openrouter_client, resolve_seed  # noqa: E402
from needle.shared.concurrency import bounded_gather  # noqa: E402
from needle.shared.llm import resolve_llm_model  # noqa: E402

out_path = sys.argv[1]
per_cell = int(sys.argv[2]) if len(sys.argv) > 2 else 10
age_buckets = ("7d", "30d", "1y")


async def main():
    now, hour_ts = current_hour()
    seed = resolve_seed(None, hour_ts)
    arxiv, europepmc = ArxivClient(), EuropePmcClient()
    llm = require_openrouter_client(resolve_llm_model(None), purpose="LLM buckets")
    stats = GenStats()
    domains = list(ARXIV_DOMAINS) + [HEALTH_DOMAIN]
    cells = [(d, a) for d in domains for a in age_buckets]
    n = per_cell * OVERSAMPLE
    windows = [_subwindows(a, now=now, count=_subwindow_count(a, n)) for _, a in cells]
    try:
        lists = await bounded_gather(
            list(zip(cells, windows, strict=True)),
            lambda item: _cell_candidates(item[0][0], item[1], arxiv=arxiv, europepmc=europepmc, n=n, seed=seed, stats=stats),
            concurrency=4,
        )
        per = {c: collections.Counter() for c in cells}
        seen, cands = set(), []
        for cell, papers in zip(cells, lists, strict=True):
            for paper in papers:
                if paper.paper_key in seen:
                    continue
                per[cell]["sampled"] += 1
                if not degrade_title(paper.title) or not paper.ids:
                    per[cell]["no_title_or_id"] += 1
                    continue
                seen.add(paper.paper_key)
                if not title_is_specific(paper.title):
                    per[cell]["generic_title"] += 1
                    continue
                cands.append((cell, replace(paper, domain=cell[0])))

        async def pair(item):
            cell, paper = item
            body = await _fetch_body(paper, arxiv=arxiv, europepmc=europepmc)
            if not body:
                return cell, "fetch", None
            outs = await asyncio.gather(*[_bucket_query(llm, b, paper, body) for b in LLM_BUCKETS])
            fails = []
            for bucket, (query, err) in zip(LLM_BUCKETS, outs, strict=True):
                if err is not None:
                    fails.append(f"{bucket}_llm_error")
                elif query is None:
                    fails.append(f"{bucket}_no_query")
                elif body_has_bad_anchor(query):
                    fails.append(f"{bucket}_bad_anchor")
                elif not query_ok(bucket, query, title=paper.title, abstract=paper.abstract):
                    fails.append(f"{bucket}_leak")
            return cell, (fails[0] if fails else None), fails

        results = await bounded_gather(cands, pair, concurrency=8)
    finally:
        await aclose_all(arxiv, europepmc, llm)
    for cell, first, fails in results:
        per[cell]["candidates"] += 1
        if first is None:
            per[cell]["accepted"] += 1
        else:
            per[cell]["rejected"] += 1
            per[cell][f"first:{first}"] += 1
            for f in fails or []:
                per[cell][f"any:{f}"] += 1
    rows = {f"{d}|{a}": dict(per[(d, a)]) for d, a in cells}
    tot = collections.Counter()
    for c in per.values():
        tot.update(c)
    print("hour", hour_ts.isoformat(), "seed", seed, "model", resolve_llm_model(None))
    print("total", dict(tot))
    for k, v in rows.items():
        print(f"{k:28s} sampled {v.get('sampled', 0):3d} generic {v.get('generic_title', 0):3d} cand {v.get('candidates', 0):3d} accepted {v.get('accepted', 0):3d} rejected {v.get('rejected', 0):3d} "
              + " ".join(f"{kk[6:]}={vv}" for kk, vv in sorted(v.items()) if kk.startswith("first:")))
    json.dump({"hour": hour_ts.isoformat(), "seed": seed, "per_cell": per_cell, "model": resolve_llm_model(None), "cells": rows, "total": dict(tot)}, open(out_path, "w"), indent=1)


asyncio.run(main())
