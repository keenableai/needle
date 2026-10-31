import asyncio
import json
import os
import re
import sys

from dotenv import load_dotenv

from needle.shared.llm import OpenRouterClient

load_dotenv("/home/yallen/needle/.env")
items_path, guideline_path, model, out_path = sys.argv[1:5]
concurrency = int(sys.argv[5]) if len(sys.argv) > 5 else 8
items = json.load(open(items_path))
guideline = open(guideline_path).read()
done = {}
if os.path.exists(out_path):
    done = {str(r["id"]): r for r in json.load(open(out_path))}
todo = [it for it in items if str(it["id"]) not in done]
print("items", len(items), "todo", len(todo), "model", model, flush=True)
llm = OpenRouterClient(api_key=os.environ["OPENROUTER_API_KEY"], model=model)
sem = asyncio.Semaphore(concurrency)
SYSTEM = guideline + "\n\nYou grade one item at a time. Reply with one JSON object only, no prose: {\"grade\": 0-4, \"note\": \"<at most 15 words>\"}."
FIELDS = ("id", "today", "query", "url", "title", "snippet")


async def one(it):
    prompt = json.dumps({k: it.get(k) for k in FIELDS}, ensure_ascii=False, indent=1)
    async with sem:
        text, err = await llm.complete(prompt, max_tokens=3000, reasoning_effort="medium", system=SYSTEM)
    if err:
        return str(it["id"]), None
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        d = json.loads(m.group(0))
        return str(it["id"]), {"id": it["id"], "grade": int(d["grade"]), "note": str(d.get("note", ""))[:120]}
    except Exception:
        return str(it["id"]), None


def save():
    json.dump(list(done.values()), open(out_path, "w"))


async def main():
    n = fails = 0
    for coro in asyncio.as_completed([one(it) for it in todo]):
        k, rec = await coro
        n += 1
        if rec is None:
            fails += 1
        else:
            done[k] = rec
        if n % 200 == 0:
            save()
            print("done", n, "fails", fails, flush=True)
    save()
    print("finished", len(done), "fails", fails, flush=True)
    await llm.aclose()


asyncio.run(main())
