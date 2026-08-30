import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from needle.shared.search.base import SearchClient
from needle.shared.search.brave import BraveClient, BraveLlmContextClient
from needle.shared.search.ceramic import CeramicClient
from needle.shared.search.exa import ExaClient
from needle.shared.search.firecrawl import FirecrawlClient
from needle.shared.search.keenable import KeenableClient
from needle.shared.search.octen import OctenClient
from needle.shared.search.parallel import ParallelClient
from needle.shared.search.perplexity import PerplexityClient
from needle.shared.search.searchapi import SearchApiClient
from needle.shared.search.serper import SerperClient
from needle.shared.search.tavily import TavilyClient
from needle.shared.search.you import YouClient


@dataclass(frozen=True)
class EngineSpec:
    key_env: str
    key_required: bool
    build: Callable[[str | None, int], SearchClient]


def _build_keenable(mode: str) -> Callable[[str | None, int], SearchClient]:
    def build(api_key: str | None, snippet_chars: int) -> SearchClient:
        return KeenableClient(api_key=api_key, mode=mode, snippet_chars=snippet_chars)

    return build


def _build_exa(search_type: str) -> Callable[[str | None, int], SearchClient]:
    def build(api_key: str | None, snippet_chars: int) -> SearchClient:
        return ExaClient(
            api_key=api_key or "",
            search_type=search_type,
            highlight_chars=snippet_chars,
        )

    return build


def _build_searchapi(engine: str) -> Callable[[str | None, int], SearchClient]:
    def build(api_key: str | None, snippet_chars: int) -> SearchClient:
        return SearchApiClient(api_key=api_key or "", engine=engine)

    return build


def _build_serper(api_key: str | None, snippet_chars: int) -> SearchClient:
    return SerperClient(api_key=api_key or "")


def _build_brave(api_key: str | None, snippet_chars: int) -> SearchClient:
    return BraveClient(api_key=api_key or "")


def _build_brave_llmcontext(api_key: str | None, snippet_chars: int) -> SearchClient:
    return BraveLlmContextClient(api_key=api_key or "", snippet_chars=snippet_chars)


def _build_parallel(mode: str) -> Callable[[str | None, int], SearchClient]:
    def build(api_key: str | None, snippet_chars: int) -> SearchClient:
        return ParallelClient(api_key=api_key or "", mode=mode)

    return build


def _build_perplexity(api_key: str | None, snippet_chars: int) -> SearchClient:
    return PerplexityClient(api_key=api_key or "")


def _build_octen(api_key: str | None, snippet_chars: int) -> SearchClient:
    return OctenClient(api_key=api_key or "")


def _build_ceramic(api_key: str | None, snippet_chars: int) -> SearchClient:
    return CeramicClient(api_key=api_key or "", description_chars=snippet_chars)


def _build_tavily(api_key: str | None, snippet_chars: int) -> SearchClient:
    return TavilyClient(api_key=api_key or "", search_depth=os.environ.get("TAVILY_DEPTH", "basic"))


def _build_you(api_key: str | None, snippet_chars: int) -> SearchClient:
    return YouClient(api_key=api_key or "")


def _build_firecrawl(api_key: str | None, snippet_chars: int) -> SearchClient:
    return FirecrawlClient(api_key=api_key or "")


ENGINES: dict[str, EngineSpec] = {
    "keenable": EngineSpec(
        key_env="KEENABLE_API_KEY", key_required=False, build=_build_keenable("pro")
    ),
    "keenable-realtime": EngineSpec(
        key_env="KEENABLE_API_KEY", key_required=False, build=_build_keenable("realtime")
    ),
    "exa": EngineSpec(key_env="EXA_API_KEY", key_required=True, build=_build_exa("auto")),
    "exa-instant": EngineSpec(
        key_env="EXA_API_KEY", key_required=True, build=_build_exa("instant")
    ),
    "google": EngineSpec(key_env="SERPER_API_KEY", key_required=True, build=_build_serper),
    "bing": EngineSpec(
        key_env="SEARCHAPI_API_KEY", key_required=True, build=_build_searchapi("bing")
    ),
    "brave": EngineSpec(key_env="BRAVE_API_KEY", key_required=True, build=_build_brave),
    "brave-llmcontext": EngineSpec(
        key_env="BRAVE_API_KEY", key_required=True, build=_build_brave_llmcontext
    ),
    "parallel": EngineSpec(
        key_env="PARALLEL_API_KEY", key_required=True, build=_build_parallel("advanced")
    ),
    "parallel-turbo": EngineSpec(
        key_env="PARALLEL_API_KEY", key_required=True, build=_build_parallel("turbo")
    ),
    "perplexity": EngineSpec(
        key_env="PERPLEXITY_API_KEY", key_required=True, build=_build_perplexity
    ),
    "tavily": EngineSpec(key_env="TAVILY_API_KEY", key_required=True, build=_build_tavily),
    "octen": EngineSpec(key_env="OCTEN_API_KEY", key_required=True, build=_build_octen),
    "ceramic": EngineSpec(key_env="CERAMIC_API_KEY", key_required=True, build=_build_ceramic),
    "you": EngineSpec(key_env="YOU_API_KEY", key_required=True, build=_build_you),
    "firecrawl": EngineSpec(key_env="FIRECRAWL_API_KEY", key_required=True, build=_build_firecrawl),
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
