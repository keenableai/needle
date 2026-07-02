"""Engine registry: adding an engine = one client class + one EngineSpec entry.

Per-engine tuning comes from env vars (not CLI flags), so the CLIs stay at a
single `--engines a,b,c` flag no matter how many engines exist.
"""

import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from keenbench.shared.search.base import SearchClient
from keenbench.shared.search.exa import ExaClient
from keenbench.shared.search.keenable import KeenableClient


@dataclass(frozen=True)
class EngineSpec:
    key_env: str
    key_required: bool
    # (api_key, snippet_chars) -> client; snippet_chars caps retrieval-side
    # evidence for engines that support it (0 = engine default)
    build: Callable[[str | None, int], SearchClient]


def _build_keenable(api_key: str | None, snippet_chars: int) -> SearchClient:
    return KeenableClient(api_key=api_key, mode=os.environ.get("KEENABLE_MODE", "pro"))


def _build_exa(api_key: str | None, snippet_chars: int) -> SearchClient:
    return ExaClient(
        api_key=api_key or "",
        max_concurrency=int(os.environ.get("EXA_CONCURRENCY", "4")),
        highlight_chars=snippet_chars,
    )


ENGINES: dict[str, EngineSpec] = {
    "keenable": EngineSpec(key_env="KEENABLE_API_KEY", key_required=False, build=_build_keenable),
    "exa": EngineSpec(key_env="EXA_API_KEY", key_required=True, build=_build_exa),
}


def build_search_clients(
    names: Iterable[str], *, snippet_chars: int = 0
) -> dict[str, SearchClient]:
    clients: dict[str, SearchClient] = {}
    for name in names:
        spec = ENGINES.get(name)
        if spec is None:
            raise ValueError(f"unknown engine {name!r} (known: {', '.join(sorted(ENGINES))})")
        api_key = os.environ.get(spec.key_env)
        if spec.key_required and not api_key:
            raise ValueError(f"{spec.key_env} is not set (needed for the {name} engine)")
        clients[name] = spec.build(api_key, snippet_chars)
    if not clients:
        raise ValueError("no engines selected")
    return clients
