import json
import os
import subprocess
import sys
import time

import yaml
from concurrent.futures import ThreadPoolExecutor

items_path, out_path = sys.argv[1], sys.argv[2]
attempts = int(sys.argv[3]) if len(sys.argv) > 3 else 2
items = json.load(open(items_path))
done = json.load(open(out_path)) if os.path.exists(out_path) else {}


def parse(text):
    try:
        doc = yaml.safe_load(text)
        if isinstance(doc, dict) and isinstance(doc.get("content"), str):
            return doc["content"].strip()
    except yaml.YAMLError:
        pass
    marker = "content: |-\n"
    i = text.find(marker)
    if i < 0:
        return None
    body = text[i + len(marker):]
    lines = []
    for line in body.split("\n"):
        if line.startswith("  "):
            lines.append(line[2:])
        elif line.strip() == "":
            lines.append("")
        else:
            break
    return "\n".join(lines).strip()


def fetch(item):
    key = str(item["id"])
    if key in done and done[key].get("content"):
        return key, done[key]
    for attempt in range(attempts):
        try:
            p = subprocess.run(["keenable", "fetch", "--max-chars", "6000", item["url"]], capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired:
            p = None
        if p is not None and p.returncode == 0:
            content = parse(p.stdout)
            if content:
                return key, {"content": content[:5000]}
            err = "no content block"
        else:
            err = (p.stderr or p.stdout).strip()[:200] if p is not None else "timeout"
        time.sleep(3 * (attempt + 1))
    return key, {"content": None, "error": err}


with ThreadPoolExecutor(max_workers=2) as ex:
    n = 0
    for key, rec in ex.map(fetch, items):
        done[key] = rec
        n += 1
        if n % 50 == 0:
            json.dump(done, open(out_path, "w"))
            print("progress", n, flush=True)
json.dump(done, open(out_path, "w"))
ok = sum(1 for r in done.values() if r.get("content"))
print("fetched", ok, "of", len(items), "failed", len(items) - ok)
