import json
import sys

ci_path, matched_path = sys.argv[1], sys.argv[2]
ms = json.load(open(matched_path))
m, base, cid = ms["matched"], ms["base"], ms["ci_diff"]
names = {"Keenable": "keenable", "Exa": "exa", "Perplexity": "perplexity", "Parallel": "parallel", "Brave (LLM ctx)": "brave-llmcontext",
         "Brave": "brave", "You.com": "you", "Linkup": "linkup", "DeepSeek": "deepseek", "Context": "context", "Kagi": "kagi",
         "Firecrawl": "firecrawl", "ChatGPT search": "chatgpt-search", "Google (Serper)": "google", "Octen": "octen",
         "Bing (SearchAPI)": "bing", "Claude search": "claude-search", "Jina": "jina", "Tavily": "tavily", "TinyFish": "tinyfish", "Ceramic": "ceramic"}
out = []
for line in open(ci_path):
    if "&" not in line:
        out.append(line)
        continue
    cells = [c.strip() for c in line.rstrip().rstrip("\\").split("&")]
    if len(cells) > 8:
        cells = cells[:3] + cells[-5:]
    e = names[cells[0]]
    cells.insert(3, f"{100 * (m[e] - base[e]):+.1f}")
    cells.insert(4, f"{100 * cid[e][0]:+.1f}, {100 * cid[e][1]:+.1f}")
    out.append(" & ".join(cells) + " \\\\\n")
open(ci_path, "w").write("".join(out))
print("ok", len(out))
