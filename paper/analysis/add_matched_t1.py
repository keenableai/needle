import json
import re
import sys

t1_path, matched_path = sys.argv[1], sys.argv[2]
ms = json.load(open(matched_path))
delta = {e: ms["matched"][e] - ms["base"][e] for e in ms["matched"]}
names = {"Keenable": "keenable", "Exa": "exa", "Perplexity": "perplexity", "Parallel": "parallel", "Brave (LLM ctx)": "brave-llmcontext",
         "Brave": "brave", "You.com": "you", "Linkup": "linkup", "DeepSeek": "deepseek", "Context": "context", "Kagi": "kagi",
         "Firecrawl": "firecrawl", "ChatGPT search": "chatgpt-search", "Google (Serper)": "google", "Octen": "octen",
         "Bing (SearchAPI)": "bing", "Claude search": "claude-search", "Jina": "jina", "Tavily": "tavily", "TinyFish": "tinyfish", "Ceramic": "ceramic"}
out = []
for line in open(t1_path):
    if "\\sharebar" not in line:
        if "\\ceilbar" in line and "\\ceilbar & \\textit{100}" not in line:
            line = line.replace("\\ceilbar &", "\\ceilbar & \\textit{100} &", 1)
        out.append(line)
        continue
    name = re.sub(r"\$\^\\d?dagger\$|\$\^\\ddagger\$", "", line.split("&")[0]).strip()
    e = names[name]
    parts = line.split("&")
    primary = float(re.search(r"\\sharebar\{([\d.]+)\}", line).group(1))
    parts.insert(2, f" {primary + 100 * delta[e]:.1f} ")
    out.append("&".join(parts))
open(t1_path, "w").write("".join(out))
print("ok")
