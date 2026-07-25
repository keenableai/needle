import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from keenbench.companyfill.canon import registrable_domain, strip_legal
from keenbench.findallmcp.harness import BackendSpec, run_task
from keenbench.shared.concurrency import bounded_gather
from keenbench.shared.llm import OpenRouterClient

JSON_RE = re.compile(r"\{.*\}", re.DOTALL)
SHOW_HN_RE = re.compile(r"^show hn[:\s]*", re.IGNORECASE)
PUNCT_RE = re.compile(r"[^a-z0-9\s]")
MIN_SUBSTRING_LEN = 8


@dataclass(frozen=True)
class GoldTask:
    text: str
    kind: str
    suite: str
    bucket: str
    entities: tuple[dict[str, Any], ...] = ()
    stat_value: float = 0.0
    stat_rel_tol: float = 0.25


def parse_answer(text: str | None) -> dict[str, Any] | None:
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-z]*\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    m = JSON_RE.search(cleaned)
    if not m:
        return None
    for candidate in (m.group(0), cleaned):
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def norm_name(raw: Any) -> str:
    s = SHOW_HN_RE.sub("", str(raw or "").lower())
    return " ".join(strip_legal(PUNCT_RE.sub(" ", s)).split())


def names_match(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    shorter, longer = sorted((a, b), key=len)
    return len(shorter) >= MIN_SUBSTRING_LEN and shorter in longer


def _item_matches(item: dict[str, Any], gold: dict[str, Any]) -> bool:
    item_name = norm_name(item.get("name") or item.get("title") or item.get("company"))
    gold_forms = [norm_name(gold.get("name"))] + [norm_name(a) for a in gold.get("aliases") or []]
    if any(names_match(item_name, g) for g in gold_forms if g):
        return True
    item_url = str(item.get("url") or "")
    for alias in gold.get("aliases") or []:
        alias = str(alias)
        if alias.startswith("http") and item_url:
            if alias.rstrip("/") == item_url.rstrip("/"):
                return True
            dom = registrable_domain(alias)
            if dom and "." in dom and registrable_domain(item_url) == dom:
                return True
    return False


def score_set(answer: dict[str, Any] | None, entities: tuple[dict[str, Any], ...]) -> dict:
    items = (answer or {}).get("items")
    if not isinstance(items, list):
        items = []
    items = [i for i in items if isinstance(i, dict)]
    matched_gold: set[int] = set()
    matched_items = 0
    for item in items:
        hit = False
        for gi, gold in enumerate(entities):
            if _item_matches(item, gold):
                matched_gold.add(gi)
                hit = True
        if hit:
            matched_items += 1
    recall = len(matched_gold) / len(entities) if entities else 0.0
    precision = matched_items / len(items) if items else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "recall": recall,
        "precision": precision,
        "f1": f1,
        "n_gold": len(entities),
        "n_returned": len(items),
        "n_matched": len(matched_gold),
    }


def score_stat(answer: dict[str, Any] | None, *, value: float, rel_tol: float) -> dict:
    raw = (answer or {}).get("value")
    if raw is None or isinstance(raw, bool):
        return {"value": None, "gold_value": value, "rel_err": None, "within_tol": False}
    try:
        got = float(raw)
    except (TypeError, ValueError):
        return {"value": None, "gold_value": value, "rel_err": None, "within_tol": False}
    rel_err = abs(got - value) / max(abs(value), 1e-9)
    return {
        "value": got,
        "gold_value": value,
        "rel_err": rel_err,
        "within_tol": rel_err <= rel_tol,
    }


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _group(scored: list[dict], key: Callable[[dict], str], metric: str) -> dict[str, dict]:
    groups: dict[str, list[dict]] = {}
    for pq in scored:
        groups.setdefault(key(pq), []).append(pq)
    return {
        name: {"n": len(pqs), metric: _mean([pq["score"] for pq in pqs])}
        for name, pqs in sorted(groups.items())
    }


def _summary(per_query: list[dict]) -> dict[str, Any]:
    scored = [pq for pq in per_query if pq["error"] is None]
    sets = [pq for pq in scored if pq["bucket"] == "enumerate"]
    stats = [pq for pq in scored if pq["bucket"] == "stat"]
    return {
        "mean_score": _mean([pq["score"] for pq in scored]),
        "set_recall": _mean([pq["detail"]["recall"] for pq in sets]),
        "set_precision": _mean([pq["detail"]["precision"] for pq in sets]),
        "set_f1": _mean([pq["detail"]["f1"] for pq in sets]),
        "stat_score": _mean([pq["score"] for pq in stats]),
        "stat_within_tol": _mean([1.0 if pq["detail"].get("within_tol") else 0.0 for pq in stats]),
        "num_scored": len(scored),
        "errors": len(per_query) - len(scored),
        "mean_spent_usd": round(_mean([pq["spent_usd"] for pq in per_query]), 4),
        "mean_tool_calls": _mean([float(sum(pq["tool_calls"].values())) for pq in per_query]),
    }


async def run_findallmcp(
    tasks: list[GoldTask],
    backends: list[BackendSpec],
    llm: OpenRouterClient,
    *,
    budgets_usd: list[float],
    max_turns: int = 20,
    concurrency: int = 2,
    trace: bool = False,
) -> dict[str, Any]:
    done = 0
    total = len(tasks) * len(backends) * len(budgets_usd)

    async def one(pair: tuple[BackendSpec, float, GoldTask]) -> dict:
        nonlocal done
        spec, budget_usd, task = pair
        run = await run_task(
            spec, llm, prompt=task.text, budget_usd=budget_usd, max_turns=max_turns, trace=trace
        )
        answer = parse_answer(run.get("answer_text"))
        pq: dict[str, Any] = {
            "backend": spec.name,
            "budget_usd": budget_usd,
            "query": task.text,
            "suite": task.suite,
            "bucket": task.bucket,
            "answer": answer,
            "spent_usd": round(run["spent_usd"], 4),
            "llm_usd": round(run["llm_usd"], 4),
            "tool_usd": round(run["tool_usd"], 4),
            "tool_calls": run["tool_calls"],
            "turns": run["turns"],
            "budget_exhausted": run["budget_exhausted"],
            "elapsed_s": run.get("elapsed_s"),
            "error": run["error"],
        }
        if "trace" in run:
            pq["trace"] = run["trace"]
        if task.kind == "set":
            detail = score_set(answer, task.entities)
            pq["score"] = detail["recall"]
        else:
            detail = score_stat(answer, value=task.stat_value, rel_tol=task.stat_rel_tol)
            rel_err = detail["rel_err"]
            pq["score"] = max(0.0, 1.0 - rel_err) if rel_err is not None else 0.0
        pq["detail"] = detail
        if answer is None and run["error"] is None:
            raw = (run.get("answer_text") or "")[:500]
            pq["error"] = {"error_type": "unparseable_answer", "error_message": raw}
        done += 1
        status = (pq["error"] or {}).get("error_type") or f"score={pq['score']:.2f}"
        print(
            f"findallmcp: [{done}/{total}] {spec.name} @${budget_usd:.2f} "
            f"{task.suite}/{task.bucket} {status} spent=${pq['spent_usd']:.2f}",
            file=sys.stderr,
        )
        return pq

    pairs = [(spec, budget, task) for spec in backends for budget in budgets_usd for task in tasks]
    results = await bounded_gather(pairs, one, concurrency=concurrency)

    backends_out: dict[str, dict[str, Any]] = {}
    for spec in backends:
        per_query = [pq for pq in results if pq["backend"] == spec.name]
        scored = [pq for pq in per_query if pq["error"] is None]
        backends_out[spec.name] = {
            **_summary(per_query),
            "by_budget": {
                f"{budget:.2f}": _summary([pq for pq in per_query if pq["budget_usd"] == budget])
                for budget in budgets_usd
            },
            "by_suite": _group(scored, lambda pq: pq["suite"], "mean_score"),
            "by_bucket": _group(scored, lambda pq: pq["bucket"], "mean_score"),
            "per_query": per_query,
        }

    return {
        "num_queries": len(tasks),
        "budgets_usd": budgets_usd,
        "agent_model": llm.model,
        "backends": backends_out,
    }
