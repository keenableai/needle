import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from keenbench.shared.identity import query_hash, query_id

FINDALLMCP_SOURCE = "findallmcp"
SUITES = ("hn", "edgar")
BUCKETS = ("enumerate", "stat")

AGENT_MODEL_ENV = "KEENBENCH_AGENT_MODEL"
DEFAULT_AGENT_MODEL = "anthropic/claude-sonnet-4.5"

MODEL_PRICES_PER_MTOK = {
    "anthropic/claude-sonnet-4.5": (3.0, 15.0),
    "anthropic/claude-sonnet-5": (3.0, 15.0),
    "anthropic/claude-haiku-4.5": (1.0, 5.0),
    "anthropic/claude-opus-4.8": (15.0, 75.0),
    "google/gemini-3.5-flash": (1.5, 9.0),
    "google/gemini-3-flash-preview": (0.5, 3.0),
    "google/gemini-3.1-flash-lite": (0.25, 1.5),
}
DEFAULT_MODEL_PRICE = (3.0, 15.0)

TOOL_PRICES_USD = {
    "search_web_pages": 0.005,
    "fetch_page_content": 0.002,
    "web_search_exa": 0.005,
    "web_fetch_exa": 0.002,
    "crawling_exa": 0.002,
    "web_search": 0.004,
    "web_fetch": 0.002,
    "map_result_set_with_llm": 0.02,
    "map_result_set_with_regex": 0.002,
    "map_result_set_with_codegen": 0.01,
    "reduce_result_set": 0.001,
    "view_result_set": 0.001,
    "merge_result_sets": 0.001,
    "rerank_result_set": 0.005,
    "submit_search_feedback": 0.0,
}
DEFAULT_TOOL_PRICE = 0.002


@dataclass(frozen=True)
class Entity:
    key: str
    name: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class Task:
    suite: str
    bucket: str
    prompt: str
    entities: tuple[Entity, ...] = ()
    stat_value: float | None = None
    stat_rel_tol: float = 0.25
    provenance: dict[str, Any] = field(default_factory=dict)


def model_price(model: str) -> tuple[float, float]:
    return MODEL_PRICES_PER_MTOK.get(model, DEFAULT_MODEL_PRICE)


def tool_price(name: str) -> float:
    return TOOL_PRICES_USD.get(name, DEFAULT_TOOL_PRICE)


def build_task_row(task: Task, *, hour_ts: datetime) -> dict[str, Any]:
    gold: dict[str, Any] = {"kind": "stat" if task.stat_value is not None else "set"}
    if task.stat_value is not None:
        gold["value"] = task.stat_value
        gold["rel_tol"] = task.stat_rel_tol
    else:
        gold["entities"] = [
            {"key": e.key, "name": e.name, "aliases": list(e.aliases)} for e in task.entities
        ]
    return {
        "query_id": query_id(task.prompt, hour_ts=hour_ts),
        "query_hash": query_hash(task.prompt),
        "query_text": task.prompt,
        "query_source": FINDALLMCP_SOURCE,
        "query_origin": {
            "bucket": task.bucket,
            "suite": task.suite,
            "provenance": task.provenance,
        },
        "gold": gold,
        "hour_ts": hour_ts.astimezone(UTC).isoformat(),
    }


def serialize_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["query_origin"] = json.dumps(row["query_origin"], sort_keys=True)
    out["gold"] = json.dumps(row["gold"], sort_keys=True)
    return out
