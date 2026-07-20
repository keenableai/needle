import asyncio
import re
from dataclasses import dataclass, field
from typing import Any

from keenbench.shared.recall import ULTIMATE, classify_misses, group_recall, ultimate_per_query
from keenbench.shared.search import SearchClient, SearchResult, latency_stats

CLUSTER_URL_RE = re.compile(r"courtlistener\.com/opinion/(\d+)/", re.IGNORECASE)
JUSTIA_US_RE = re.compile(
    r"supreme\.justia\.com/cases/federal/us/(\d{1,4})/(\d{1,5})", re.IGNORECASE
)
JUSTIA_APPELLATE_RE = re.compile(
    r"law\.justia\.com/cases/federal/appellate-courts/[a-z0-9]+/(\d{2}-\d{1,5})", re.IGNORECASE
)
CITE_RE = re.compile(r"(\d{1,4})\s+([A-Za-z][\w.'’]*(?:\s[A-Za-z][\w.'’]*){0,3}?)\s+(\d{1,5})")
DOCKET_RE = re.compile(r"\b(\d{2})\s?[-–]\s?(\d{1,5})\b|\b(\d{2})([aA])(\d{1,4})\b")
CFR_TEXT_RE = re.compile(
    r"(\d{1,2})\s*C\.?\s?F\.?\s?R\.?\s*(?:part\s*)?(?:§+\s*)?(\d+\.[\w.\-]+)", re.IGNORECASE
)
CFR_URL_RES = [
    re.compile(r"law\.cornell\.edu/cfr/text/(\d{1,2})/(\d+\.[\w.\-]+)", re.IGNORECASE),
    re.compile(r"ecfr\.gov/[^\s]*title-(\d{1,2})/[^\s]*section-(\d+\.[\w.\-]+)", re.IGNORECASE),
    re.compile(r"title-(\d{1,2})[^\s]*/section-(\d+\.[\w.\-]+)", re.IGNORECASE),
]

_REPORTER_ALLOWED = frozenset(
    "us sct led led2d f f2d f3d f4th fsupp fsupp2d fsupp3d fappx fedappx wl"
    " a a2d a3d p p2d p3d ne ne2d ne3d nw nw2d nw3d so so2d so3d se se2d se3d"
    " sw sw2d sw3d cal cal2d cal3d cal4th cal5th nys nys2d nys3d us l ed".split()
)


def norm_reporter(raw: str) -> str:
    return re.sub(r"[^a-z0-9]", "", raw.lower())


def norm_citation(raw: str) -> str | None:
    m = re.match(r"^\s*(\d{1,4})\s+(.+?)\s+(\d{1,5})\s*$", raw)
    if not m:
        return None
    reporter = norm_reporter(m.group(2))
    if not reporter:
        return None
    return f"{m.group(1)}:{reporter}:{m.group(3)}"


def norm_docket(raw: str) -> str:
    return re.sub(r"[\s–]", "", raw.replace("–", "-")).lower()


@dataclass
class LegalIds:
    clusters: set[str] = field(default_factory=set)
    cites: set[str] = field(default_factory=set)
    dockets: set[str] = field(default_factory=set)
    cfr: set[str] = field(default_factory=set)

    def as_match_dict(self) -> dict[str, list[str]]:
        out = {}
        for key, values in (
            ("cluster", self.clusters),
            ("cites", self.cites),
            ("docket", self.dockets),
            ("cfr", self.cfr),
        ):
            if values:
                out[key] = sorted(values)
        return out


def _capped(result: SearchResult, snippet_chars: int) -> str:
    snippet = result.snippet or ""
    if snippet_chars > 0:
        snippet = snippet[:snippet_chars]
    return " ".join(part for part in (result.title, snippet) if part)


def extract_legal_ids(result: SearchResult, *, snippet_chars: int) -> LegalIds:
    url = result.url or ""
    text = _capped(result, snippet_chars)
    ids = LegalIds()
    for m in CLUSTER_URL_RE.finditer(url):
        ids.clusters.add(m.group(1))
    for m in JUSTIA_US_RE.finditer(url):
        ids.cites.add(f"{m.group(1)}:us:{m.group(2)}")
    for m in JUSTIA_APPELLATE_RE.finditer(url):
        ids.dockets.add(norm_docket(m.group(1)))
    for m in CITE_RE.finditer(text):
        reporter = norm_reporter(m.group(2))
        if reporter in _REPORTER_ALLOWED:
            ids.cites.add(f"{m.group(1)}:{reporter}:{m.group(3)}")
    for m in DOCKET_RE.finditer(f"{text} {url}"):
        if m.group(1):
            ids.dockets.add(f"{m.group(1)}-{m.group(2)}")
        else:
            ids.dockets.add(f"{m.group(3)}a{m.group(5)}".lower())
    for m in CFR_TEXT_RE.finditer(text):
        ids.cfr.add(f"{int(m.group(1))}:{m.group(2).rstrip('.')}")
    for pat in CFR_URL_RES:
        for m in pat.finditer(url):
            ids.cfr.add(f"{int(m.group(1))}:{m.group(2).rstrip('.')}")
    return ids


@dataclass(frozen=True)
class GoldLegal:
    text: str
    case_key: str
    bucket: str
    syntax: str
    cluster: str = ""
    docket: str = ""
    cites: tuple[str, ...] = ()
    cfr: str = ""
    party_tokens: tuple[str, ...] = ()
    court: str = ""


def ids_match(gold: GoldLegal, found: LegalIds, *, result_text: str) -> bool:
    if gold.cluster and gold.cluster in found.clusters:
        return True
    gold_cites = {c for c in (norm_citation(raw) for raw in gold.cites) if c}
    if gold_cites & found.cites:
        return True
    if gold.cfr and gold.cfr in found.cfr:
        return True
    if gold.docket and norm_docket(gold.docket) in found.dockets:
        lowered = result_text.lower()
        if any(token in lowered for token in gold.party_tokens):
            return True
    return False


def _summary(per_query: list[dict], latency: dict | None) -> dict[str, Any]:
    scored = [pq for pq in per_query if pq["search_error"] is None]
    hits = [pq for pq in scored if pq["hit_rank"] is not None]
    return {
        "recall_at_k": len(hits) / len(scored) if scored else 0.0,
        "mrr_at_k": (sum(1.0 / pq["hit_rank"] for pq in hits) / len(scored) if scored else 0.0),
        "num_scored": len(scored),
        "search_errors": sum(1 for pq in per_query if pq["search_error"] is not None),
        "latency": latency,
        "by_bucket": group_recall(scored, lambda pq: pq["bucket"]),
        "by_syntax": group_recall(scored, lambda pq: pq["syntax"]),
        "by_court": group_recall([pq for pq in scored if pq["court"]], lambda pq: pq["court"]),
        "per_query": per_query,
    }


async def run_legal(
    queries: list[GoldLegal],
    engines: dict[str, SearchClient],
    *,
    num_results: int = 5,
    snippet_chars: int = 500,
) -> dict[str, Any]:
    engine_names = list(engines)

    def eval_engine(query: GoldLegal, results: list[SearchResult] | None, err: Any) -> dict:
        pq: dict[str, Any] = {
            "query": query.text,
            "case_key": query.case_key,
            "bucket": query.bucket,
            "syntax": query.syntax,
            "court": query.court,
            "hit_rank": None,
            "n_results": 0,
            "results": [],
            "search_error": err,
        }
        if err is not None:
            return pq
        results = results or []
        pq["n_results"] = len(results)
        found = [extract_legal_ids(r, snippet_chars=snippet_chars) for r in results]
        pq["results"] = [
            {"url": r.url, "title": r.title, "ids": f.as_match_dict()}
            for r, f in zip(results, found, strict=True)
        ]
        for rank, (r, f) in enumerate(zip(results, found, strict=True), start=1):
            if ids_match(query, f, result_text=f"{_capped(r, snippet_chars)} {r.url or ''}"):
                pq["hit_rank"] = rank
                break
        return pq

    async def run_query(query: GoldLegal) -> list[dict]:
        searches = await asyncio.gather(
            *[engines[n].search(query.text, num_results=num_results) for n in engine_names]
        )
        return [eval_engine(query, r, e) for r, e in searches]

    query_outs = await asyncio.gather(*[run_query(q) for q in queries])

    engines_out: dict[str, dict[str, Any]] = {}
    for idx, name in enumerate(engine_names):
        per_query = [entries[idx] for entries in query_outs]
        engines_out[name] = _summary(per_query, latency_stats(engines[name].latencies_ms))
    engines_out[ULTIMATE] = _summary(ultimate_per_query(query_outs, cap=num_results), None)

    classify_misses(query_outs, engine_names, engines_out)

    return {
        "num_queries": len(queries),
        "num_results": num_results,
        "snippet_chars": snippet_chars,
        "engines": engines_out,
    }
