from needle.shared.search.base import (
    DEFAULT_SNIPPET_CHARS,
    HttpSearchClient,
    SearchClient,
    SearchResult,
    capped_snippet,
    latency_stats,
    search_all,
    titled_snippet,
)
from needle.shared.search.brave import BraveClient
from needle.shared.search.ceramic import CeramicClient
from needle.shared.search.exa import ExaClient
from needle.shared.search.factory import build_search_clients
from needle.shared.search.firecrawl import FirecrawlClient
from needle.shared.search.keenable import KeenableClient
from needle.shared.search.octen import OctenClient
from needle.shared.search.parallel import ParallelClient
from needle.shared.search.perplexity import PerplexityClient
from needle.shared.search.searchapi import SearchApiClient
from needle.shared.search.serper import SerperClient
from needle.shared.search.tavily import TavilyClient
from needle.shared.search.you import YouClient

__all__ = [
    "BraveClient",
    "CeramicClient",
    "DEFAULT_SNIPPET_CHARS",
    "ExaClient",
    "FirecrawlClient",
    "HttpSearchClient",
    "KeenableClient",
    "OctenClient",
    "ParallelClient",
    "PerplexityClient",
    "SearchApiClient",
    "SearchClient",
    "SearchResult",
    "SerperClient",
    "TavilyClient",
    "YouClient",
    "build_search_clients",
    "capped_snippet",
    "latency_stats",
    "search_all",
    "titled_snippet",
]
