import asyncio
import os

import pytest
from dotenv import dotenv_values

from keenbench.shared.judge import RATING_LABELS, classify_query, judge_one
from keenbench.shared.llm import OpenRouterClient, resolve_judge_model

API_KEY = os.environ.get("OPENROUTER_API_KEY") or dotenv_values().get("OPENROUTER_API_KEY")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not API_KEY, reason="OPENROUTER_API_KEY is not set"),
]

TODAY = "2026-08-11"

CASES = [
    (
        "who wrote the novel Nineteen Eighty-Four",
        {
            "url": "https://en.wikipedia.org/wiki/Nineteen_Eighty-Four",
            "title": "Nineteen Eighty-Four - Wikipedia",
            "content": (
                "Nineteen Eighty-Four is a dystopian novel by the English writer George "
                "Orwell, published on 8 June 1949 by Secker & Warburg as Orwell's ninth "
                "and final completed book. The story takes place in an imagined future "
                "where Britain, now known as Airstrip One, is part of the totalitarian "
                "superstate Oceania, ruled by the Party under the dictatorship of Big "
                "Brother. Orwell wrote the novel on the Scottish island of Jura between "
                "1946 and 1948 while critically ill with tuberculosis."
            ),
        },
        3,
        4,
    ),
    (
        "how to install python on windows",
        {
            "url": "https://sweettreats.example.com/chocolate-chip-cookies",
            "title": "The Best Chocolate Chip Cookie Recipe",
            "content": (
                "These chocolate chip cookies are soft, chewy, and loaded with melty "
                "chocolate. Cream the butter with brown sugar, add eggs and vanilla, "
                "then fold in flour, baking soda, and a generous amount of chocolate "
                "chips. Bake at 375F for 10 minutes until the edges are golden."
            ),
        },
        0,
        1,
    ),
    (
        "pandas dataframe documentation site:pandas.pydata.org",
        {
            "url": "https://www.geeksforgeeks.org/python-pandas-dataframe/",
            "title": "Python Pandas DataFrame - GeeksforGeeks",
            "content": (
                "A Pandas DataFrame is a two-dimensional, size-mutable, potentially "
                "heterogeneous tabular data structure with labeled axes. You can create "
                "a DataFrame from lists, dictionaries, or NumPy arrays, select rows "
                "with loc and iloc, and filter with boolean indexing."
            ),
        },
        0,
        0,
    ),
    (
        '"crimson velocity engine" review',
        {
            "url": "https://autonews.example.com/v8-engines-explained",
            "title": "How Modern V8 Engines Work",
            "content": (
                "Modern V8 engines balance power and efficiency through variable valve "
                "timing, direct injection, and cylinder deactivation. This guide "
                "explains firing order, crankshaft design, and why turbocharged V8s "
                "dominate performance cars today."
            ),
        },
        0,
        0,
    ),
    (
        "iphone 16 vs samsung galaxy s25 camera and battery comparison",
        {
            "url": "https://phonereviews.example.com/iphone-16-camera",
            "title": "iPhone 16 Camera Review",
            "content": (
                "The iPhone 16's 48MP main sensor captures excellent detail in daylight "
                "and its new Photographic Styles engine improves skin tones. Low-light "
                "shots are cleaner than last year thanks to a faster aperture. This "
                "review covers the camera only; battery testing is ongoing."
            ),
        },
        1,
        2,
    ),
]


def _make_llm():
    return OpenRouterClient(api_key=API_KEY, model=resolve_judge_model(None))


async def test_judge_end_to_end_pairs():
    llm = _make_llm()
    try:
        results = await asyncio.gather(
            *[judge_one(llm, query, today=TODAY, **doc) for query, doc, _, _ in CASES]
        )
    finally:
        await llm.aclose()
    for (query, _, lo, hi), (judgement, err) in zip(CASES, results, strict=True):
        assert err is None, f"{query}: {err}"
        assert judgement is not None, query
        assert lo <= judgement.rating <= hi, (
            f"{query}: rating {judgement.rating}, reasoning: {judgement.reasoning}"
        )
        assert judgement.label == RATING_LABELS[judgement.rating], (
            f"{query}: label {judgement.label} inconsistent with rating {judgement.rating}"
        )
        assert judgement.reasoning


async def test_classify_query_end_to_end():
    llm = _make_llm()
    try:
        specific, err_s = await classify_query(
            llm, "who won the monaco grand prix yesterday", today=TODAY
        )
        broad, err_b = await classify_query(llm, "what is photosynthesis", today=TODAY)
    finally:
        await llm.aclose()
    assert err_s is None and specific is not None
    assert specific.query_type == "specific"
    assert specific.query_content_archetype == "ephemeral"
    assert specific.query_main_aspects
    assert err_b is None and broad is not None
    assert broad.query_type == "broad"
    assert broad.query_content_archetype == "evergreen"
