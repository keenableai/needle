import asyncio
import json
import os
import re
import sys

from dotenv import load_dotenv

from needle.shared.llm import OpenRouterClient

load_dotenv("/home/yallen/needle/.env")
raters_dir, model, out_path = sys.argv[1:4]
concurrency = int(sys.argv[4]) if len(sys.argv) > 4 else 8
items = json.load(open(f"{raters_dir}/items_key.json"))
pages = json.load(open(f"{raters_dir}/pages.json"))
guideline = open(f"{raters_dir}/guideline.md").read()
done = json.load(open(out_path)) if os.path.exists(out_path) else {}
todo = [it for it in items if str(it["id"]) not in done]
print("items", len(items), "todo", len(todo), "model", model, flush=True)
llm = OpenRouterClient(api_key=os.environ["OPENROUTER_API_KEY"], model=model)
sem = asyncio.Semaphore(concurrency)
SYSTEM = guideline + "\n\nYou grade one item at a time. Reply with one JSON object only, no prose: {\"snippet_grade\": 0-4, \"page_grade\": 0-4, \"page_missing\": true|false, \"note\": \"<at most 15 words>\"}."


def prompt_for(it):
    page = (pages.get(str(it["id"])) or {}).get("content") or ""
    body = {"id": it["id"], "today": it["today"], "query": it["query"], "url": it["url"], "title": it["title"], "snippet": it["snippet"], "page_excerpt": page[:3000]}
    return json.dumps(body, ensure_ascii=False, indent=1)


def parse(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
        return {"snippet_grade": int(d["snippet_grade"]), "page_grade": int(d["page_grade"]), "page_missing": bool(d.get("page_missing", False)), "note": str(d.get("note", ""))[:120]}
    except Exception:
        return None


async def one(it):
    async with sem:
        text, err = await llm.complete(prompt_for(it), max_tokens=4000, reasoning_effort="medium", system=SYSTEM)
    if err:
        return str(it["id"]), {"error": err}
    rec = parse(text)
    return str(it["id"]), (rec or {"error": {"error_type": "parse", "error_message": (text or "")[:200]}})


async def main():
    n = 0
    for coro in asyncio.as_completed([one(it) for it in todo]):
        k, rec = await coro
        done[k] = rec
        n += 1
        if n % 50 == 0:
            json.dump(done, open(out_path, "w"))
            print("done", n, flush=True)
    json.dump(done, open(out_path, "w"))
    errs = sum(1 for v in done.values() if "error" in v)
    print("finished", len(done), "errors", errs, flush=True)
    await llm.aclose()


asyncio.run(main())
