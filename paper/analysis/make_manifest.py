import glob
import json
import os
import sys

here = os.path.dirname(os.path.abspath(__file__))
pairs = json.load(open(os.path.join(here, "audit", "adjacent_pairs.json")))
audits = sorted(os.path.relpath(p, here) for p in glob.glob(os.path.join(here, "audit", "**", "*"), recursive=True) if os.path.isfile(p))
manifest = {
    "paper_commit": sys.argv[1],
    "results_dataset": {"repo": "keenable-ai/needle-results", "revision": "6a5be09d6d2eed18227b8e1d2c0656bc1c14e5be"},
    "scoring_rules": {
        "service_side_failure": "scored zero",
        "account_side_failure": "excluded (perplexity, exa, kagi, parallel, claude-search families)",
        "site_hit": "requested host only",
        "money_band": 0.001,
        "money_readings": ["prose", "plain figure", "unit-less table figure", "parenthesized loss"],
        "money_backstop": False,
        "duplicate_penalty": "every query",
        "snippet_cap_chars": 2000,
    },
    "judge": {"model": "openai/gpt-6-luna", "provider": "openrouter", "temperature": 0, "reasoning_effort": "high"},
    "second_judge_and_raters": "Claude Opus 5.5",
    "results": {
        "table_results": {"source": "history_v3.jsonl", "rule": "runs since 2026-10-17 in which every listed configuration ran", "runs": pairs["runs"], "engines": pairs["order"]},
        "table_ci": {"source": "history_v3.jsonl + audit/matched_pairs.json", "same_runs_as": "table_results"},
        "matched_support_full_window": {"file": "audit/matched_pairs.json", "news_runs": 256, "matched_query_runs": 6801},
        "figure_results_a": {"source": "history_v3.jsonl", "bench": "scholar", "window_days": 30, "window_end": "2026-10-29"},
        "figure_results_b": {"source": "history_v3.jsonl", "weeks": "2026-W36..2026-W43"},
        "adjacent_pairs": {"files": ["audit/adjacent_pairs.json", "audit/adjacent_pairs_day.json"], "resamples": 2000},
        "lag_subset": {"file": "audit/lag_subset.json", "runs": 249, "queries": 4959},
        "finance_bias": {"file": "audit/finance_bias.json"},
        "raters": {"dir": "audit/raters", "items": 1200},
        "caselaw_identity": {"dir": "audit/caselaw_identity", "hits": 100},
        "list_level_raters": {"dir": "audit/lists", "file": "audit/list_level.json", "pools": 20, "results": 1150},
        "ceramic_rawops": {"file": "audit/ceramic_rawops.json", "queries": 20},
        "legal_target_only": {"file": "audit/legal_target_only.json"},
        "rare_quoted": {"file": "audit/rare_quoted.json"},
        "bench_weights": {"file": "audit/bench_weights.json"},
        "scholar_strata": {"file": "audit/scholar_strata.json"},
        "list_pair_diffs": {"file": "audit/list_pair_diffs.json"},
        "pairs_survive": {"file": "audit/pairs_survive.json"},
        "ceiling_drop": {"file": "audit/ceiling_drop.json"},
        "unquoted_overall": {"file": "audit/unquoted_overall.json"},
        "failure_profile": {"file": "audit/failure_profile.json", "records": 6530},
        "trunc_ci": {"file": "audit/trunc_ci.json"},
    },
    "not_recoverable": ["published date returned by each API for news results", "code revision per run before 2026-10-30"],
    "audit_files": audits,
}
json.dump(manifest, open(os.path.join(here, "manifest.json"), "w"), indent=1)
print("manifest", len(audits), "audit files")
