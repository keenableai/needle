from needle.finance.sources import html_text, quarterly_facts


def _fact(val, start, end, fy, fp, form="10-Q"):
    return {"val": val, "start": start, "end": end, "fy": fy, "fp": fp, "form": form}


FACTS = {
    "NetIncomeLoss": {
        "units": {
            "USD": [
                _fact(100, "2026-01-01", "2026-03-31", 2026, "Q1"),
                _fact(90, "2025-10-01", "2025-12-31", 2026, "Q1", form="10-K"),
                _fact(80, "2025-07-01", "2025-09-30", 2025, "Q3"),
                _fact(999, "2025-01-01", "2025-09-30", 2025, "Q3"),
                _fact(70, "2025-04-01", "2025-06-30", 2025, "Q2"),
                _fact(None, "2025-01-01", "2025-03-31", 2025, "Q1"),
            ]
        }
    }
}


def test_quarterly_facts_filters_and_orders():
    facts = quarterly_facts(FACTS, "net_income")
    assert [(f.fy, f.fp, f.value) for f in facts] == [
        (2026, "Q1", 100.0),
        (2025, "Q3", 80.0),
        (2025, "Q2", 70.0),
    ]


def test_quarterly_facts_rejects_ytd_spans():
    values = [f.value for f in quarterly_facts(FACTS, "net_income")]
    assert 999.0 not in values


def test_quarterly_facts_eps_uses_per_share_unit():
    facts = {
        "EarningsPerShareDiluted": {
            "units": {"USD/shares": [_fact(1.05, "2026-01-01", "2026-03-31", 2026, "Q1")]}
        }
    }
    out = quarterly_facts(facts, "eps_diluted")
    assert [(f.fp, f.value) for f in out] == [("Q1", 1.05)]


def test_html_text_strips_markup():
    html = "<html><head><title>x</title></head><body><p>Net income was <b>$5</b></p><script>bad()</script></body></html>"
    assert html_text(html) == "Net income was $5"
