import asyncio
import sys

from keenbench.scholar.generate import QUERY_BUCKETS, GenStats, run_generate
from keenbench.scholar.idconv import IdConverter
from keenbench.scholar.models import AGE_BUCKETS
from keenbench.scholar.projection import LLM_BUCKETS
from keenbench.scholar.score import GoldPaper, run_papers
from keenbench.scholar.sources import ArxivClient, EuropePmcClient
from keenbench.shared.cli import (
    aclose_all,
    build_clients_or_exit,
    current_hour,
    has_gold_ids,
    load_gold_rows,
    parse_known_csv,
    require_openrouter_client,
    resolve_seed,
    sample_or_exit,
)
from keenbench.shared.io import serialize_row, write_json, write_jsonl
from keenbench.shared.llm import resolve_llm_model
from keenbench.shared.search import DEFAULT_SNIPPET_CHARS

KNOWN_SUITES = ("arxiv", "europepmc")


def _gold_paper(row: dict) -> GoldPaper:
    gold = row["gold"]
    origin = row.get("query_origin") or {}
    return GoldPaper(
        text=str(row["query_text"]),
        paper_key=str(gold.get("paper_key") or ""),
        ids={k: str(v) for k, v in (gold.get("ids") or {}).items()},
        bucket=str(origin.get("bucket") or "unknown"),
    )


class Scholar:
    def generate(
        self,
        out: str = "-",
        suites: str | tuple[str, ...] = "arxiv,europepmc",
        age_buckets: str | tuple[str, ...] = "7d,30d,1y",
        buckets: str | tuple[str, ...] = ",".join(QUERY_BUCKETS),
        per_cell: int = 10,
        seed: int | None = None,
        llm_model: str | None = None,
        body_concurrency: int = 8,
    ) -> None:
        suite_names = parse_known_csv(suites, KNOWN_SUITES, flag="--suites")
        age_names = parse_known_csv(age_buckets, AGE_BUCKETS, flag="--age-buckets")
        bucket_names = parse_known_csv(buckets, QUERY_BUCKETS, flag="--buckets")

        now, hour_ts = current_hour()
        seed = resolve_seed(seed, hour_ts)

        arxiv = ArxivClient() if "arxiv" in suite_names else None
        europepmc = EuropePmcClient() if "europepmc" in suite_names else None

        llm = None
        if any(b in LLM_BUCKETS for b in bucket_names):
            llm = require_openrouter_client(resolve_llm_model(llm_model), purpose="LLM buckets")

        async def _go() -> tuple[list[dict], GenStats]:
            try:
                return await run_generate(
                    arxiv=arxiv,
                    europepmc=europepmc,
                    llm=llm,
                    hour_ts=hour_ts,
                    now=now,
                    age_buckets=age_names,
                    per_cell=per_cell,
                    seed=seed,
                    buckets=bucket_names,
                    body_concurrency=body_concurrency,
                )
            finally:
                await aclose_all(arxiv, europepmc, llm)

        rows, stats = asyncio.run(_go())
        write_jsonl([serialize_row(r) for r in rows], out)
        rows_str = ", ".join(f"{b}={stats.rows.get(b, 0)}" for b in bucket_names)
        drops_str = ", ".join(f"{k}={v}" for k, v in sorted(stats.drops.items())) or "none"
        print(
            f"scholar: {sum(stats.rows.values())} queries from {stats.papers} paired "
            f"papers ({rows_str}; {stats.candidates} candidates; "
            f"generic_title={stats.generic_title}; drops: {drops_str}; "
            f"short_cells={stats.short_cells})",
            file=sys.stderr,
        )
        if stats.drop_samples:
            samples = "; ".join(f"{k}: {v}" for k, v in sorted(stats.drop_samples.items()))
            print(f"scholar first drop errors: {samples}", file=sys.stderr)

    def run(
        self,
        queries: str,
        out: str = "-",
        engines: str | tuple[str, ...] = "keenable,exa",
        num_results: int = 5,
        snippet_chars: int = DEFAULT_SNIPPET_CHARS,
        limit: int = 0,
        sample: str = "stratified",
        seed: int | None = None,
        resolve_pmcids: bool = True,
    ) -> None:
        rows = load_gold_rows(queries, bench="scholar", gold_ok=has_gold_ids)
        rows = sample_or_exit(
            rows,
            limit,
            seed,
            strategy=sample,
            key=lambda r: (
                f"{r['query_origin'].get('bucket', '?')}:{r['gold'].get('age_bucket', '?')}"
            ),
        )
        gold_papers = [_gold_paper(r) for r in rows]

        clients = build_clients_or_exit(engines, snippet_chars=snippet_chars)
        need_idconv = resolve_pmcids and any("pmid" in g.ids for g in gold_papers)
        idconv = IdConverter() if need_idconv else None

        async def _go() -> dict:
            try:
                return await run_papers(
                    gold_papers,
                    clients,
                    num_results=num_results,
                    snippet_chars=snippet_chars,
                    idconv=idconv,
                )
            finally:
                await aclose_all(*clients.values(), idconv)

        report = asyncio.run(_go())
        write_json(report, out)

        print(
            f"\nscholar: {report['num_queries']} queries, top-{num_results}",
            file=sys.stderr,
        )
        for name, e in report["engines"].items():
            bucket_strs = []
            for bucket in QUERY_BUCKETS:
                recall = e["by_bucket"].get(bucket, {}).get("recall_at_k")
                if recall is not None:
                    bucket_strs.append(f"{bucket} = {recall:.3f}")
            mrr_str = f"{e['mrr_at_k']:.4f}" if e["mrr_at_k"] is not None else "n/a"
            print(
                f"  {name:10s} recall@{num_results} = {e['recall_at_k']:.4f}  "
                f"MRR = {mrr_str}  "
                f"({', '.join(bucket_strs) or 'no buckets'}; "
                f"{e['num_scored']}/{report['num_queries']} scored; "
                f"{e['search_errors']} search errs; "
                f"misses: {e['misses_system_specific']} sys / {e['misses_universal']} univ)",
                file=sys.stderr,
            )
