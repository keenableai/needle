import pytest
from jinja2 import UndefinedError

from keenbench.shared.prompts import render_prompt


def test_render_projection_prompt():
    out = render_prompt(
        "keenbench.news",
        "projection.jinja",
        today="2020-01-01",
        source_kind="rss_news",
        title="t",
        summary="s",
        url="u",
    )
    assert "Today's date: 2020-01-01" in out
    assert "Source kind: rss_news" in out
    assert "NO_NEWS_EVENT" in out


def test_missing_var_raises():
    with pytest.raises(UndefinedError):
        render_prompt("keenbench.news", "projection.jinja", today="x")
