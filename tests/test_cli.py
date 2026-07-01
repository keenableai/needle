import pytest

from keenbench.freshstream.cli import Freshstream
from keenbench.shared.llm import OpenRouterClient


def test_run_rejects_unsupported_source():
    with pytest.raises(SystemExit):
        Freshstream().run(source="trending")


def test_openrouter_default_temperature_is_deterministic():
    assert OpenRouterClient(api_key="x", model="m").temperature == 0.0
