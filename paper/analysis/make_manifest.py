import glob
import json
import os
import sys

here = os.path.dirname(os.path.abspath(__file__))
HISTORY = "gh-pages data/history.jsonl, rows up to 2026-10-29T11:53Z"
pairs = json.load(open(os.path.join(here, "audit", "adjacent_pairs.json")))
audits = sorted(os.path.relpath(p, here) for p in glob.glob(os.path.join(here, "audit", "**", "*"), recursive=True) if os.path.isfile(p))
manifest = {
    "paper_commit": sys.argv[1],
    "results_dataset": {"repo": "keenable-ai/needle-results", "revision": "6a5be09d6d2eed18227b8e1d2c0656bc1c14e5be"},
    "scoring_rules": {
        "service_side_failure": "scored zero",
        "account_side_failure": "excluded (classified per error record by needle.shared.search.errors.account_side)",
        "site_hit": "gold identity on any host",
        "money_band": 0.001,
        "money_readings": ["prose", "plain figure", "unit-less table figure", "parenthesized loss"],
        "money_backstop": False,
        "duplicate_penalty": "skipped for site: queries",
        "snippet_cap_chars": 2000,
        "dashboard_rows": [
            "news and rare runs before 2026-10-28T11:05Z score every failed request zero",
            "news and rare runs from 2026-10-28T11:05Z to 2026-10-31T23:47Z leave every failed request out of the mean",
            "11 of the 12 scholar runs of table_results match DOIs with the previous scholar matcher",
        ],
    },
    "judge": {"model": "openai/gpt-6-luna", "provider": "openrouter", "temperature": 0, "reasoning_effort": "high"},
    "second_judge": "Claude Opus 5.5",
    "raters": ["Claude Opus 5.5", "Gemini 4", "Grok 4.7"],
    "results": {
        "table_results": {"source": HISTORY, "rule": "runs since 2026-10-17 in which every listed configuration ran", "runs": pairs["runs"], "engines": pairs["order"]},
        "table_ci": {"source": [HISTORY, "audit/matched_pairs.json"], "same_runs_as": "table_results"},
        "matched_support": {"file": "audit/matched_pairs.json"},
        "figure_results_a": {"source": HISTORY, "bench": "scholar", "window_days": 30, "window_end": "2026-10-29"},
        "figure_results_b": {"source": HISTORY, "weeks": "2026-W36..2026-W43"},
        "adjacent_pairs": {"files": ["audit/adjacent_pairs.json", "audit/adjacent_pairs_day.json"], "resamples": 2000},
        "lag_subset": {"file": "audit/lag_subset.json"},
        "finance_bias": {"file": "audit/finance_bias_table1.json"},
        "raters": {"dir": "audit/raters"},
        "caselaw_identity": {"dir": "audit/caselaw_identity"},
        "list_level_raters": {"dir": "audit/lists100", "files": ["audit/lists100/list_level_gemini.json", "audit/lists100/list_level_grok.json"]},
        "ceramic_rawops": {"file": "audit/ceramic_rawops.json"},
        "legal_target_only": {"file": "audit/legal_target_only.json"},
        "rare_quoted": {"file": "audit/rare_quoted.json"},
        "bench_weights": {"file": "audit/bench_weights.json"},
        "scholar_strata": {"file": "audit/scholar_strata.json"},
        "list_pair_diffs": {"files": ["audit/lists100/list_pair_diffs_gemini.json", "audit/lists100/list_pair_diffs_grok.json"]},
        "pairs_survive": {"file": "audit/pairs_survive.json"},
        "ceiling_drop": {"file": "audit/ceiling_drop.json"},
        "unquoted_overall": {"file": "audit/unquoted_overall.json"},
        "failure_profile": {"file": "audit/failure_profile.json"},
        "trunc_ci": {"file": "audit/trunc_ci.json"},
        "later_day": {"file": "audit/later_day.json"},
        "cluster_pairs": {"file": "audit/cluster_pairs.json"},
        "repeat_queries": {"file": "audit/repeat_queries.json"},
        "paired_variants": {"dir": "audit/paired", "table": "table_paired.tex"},
        "no_table_reading": {"file": "audit/no_table_reading.json"},
    },
    "not_recoverable": ["published date returned by each API for news results", "code revision per run before 2026-10-30"],
    "audit_files": audits,
}
json.dump(manifest, open(os.path.join(here, "manifest.json"), "w"), indent=1)
print("manifest", len(audits), "audit files")
