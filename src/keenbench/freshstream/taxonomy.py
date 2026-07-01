import json
from typing import Any

TOPICAL_DOMAINS: tuple[str, ...] = (
    "sports",
    "finance",
    "tech",
    "health",
    "weather",
    "local_civic",
    "entertainment",
    "gaming",
    "commerce",
    "government",
    "science",
    "education",
    "travel",
    "automotive",
    "other",
)

TRENDS_CATEGORY_TO_DOMAIN: dict[str, str] = {
    "sports": "sports",
    "entertainment": "entertainment",
    "law_and_government": "government",
    "politics": "government",
    "business_and_finance": "finance",
    "games": "gaming",
    "health": "health",
    "technology": "tech",
    "science": "science",
    "climate": "science",
    "shopping": "commerce",
    "beauty_and_fashion": "commerce",
    "food_and_drink": "commerce",
    "autos_and_vehicles": "automotive",
}


def trends_category_to_topical_domain(categories: Any) -> str:
    if not categories:
        return "other"
    if isinstance(categories, str):
        try:
            cats = json.loads(categories)
        except json.JSONDecodeError:
            return "other"
    else:
        cats = list(categories)
    for c in cats or []:
        key = str(c).lower()
        if key in TRENDS_CATEGORY_TO_DOMAIN:
            return TRENDS_CATEGORY_TO_DOMAIN[key]
    return "other"
