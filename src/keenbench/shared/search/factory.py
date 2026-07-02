import os
from collections.abc import Iterable

from keenbench.shared.search.base import SearchClient
from keenbench.shared.search.exa import ExaClient
from keenbench.shared.search.keenable import KeenableClient


def build_search_clients(
    names: Iterable[str],
    *,
    keenable_mode: str = "pro",
    exa_concurrency: int = 4,
    exa_highlight_chars: int = 0,
) -> dict[str, SearchClient]:
    clients: dict[str, SearchClient] = {}
    for name in names:
        if name == "keenable":
            clients[name] = KeenableClient(
                api_key=os.environ.get("KEENABLE_API_KEY"), mode=keenable_mode
            )
        elif name == "exa":
            exa_key = os.environ.get("EXA_API_KEY")
            if not exa_key:
                raise ValueError("EXA_API_KEY is not set (needed for the exa engine)")
            clients[name] = ExaClient(
                api_key=exa_key,
                max_concurrency=exa_concurrency,
                highlight_chars=exa_highlight_chars,
            )
        else:
            raise ValueError(f"unknown engine {name!r} (known: keenable, exa)")
    if not clients:
        raise ValueError("no engines selected")
    return clients
