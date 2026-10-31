import asyncio
import glob
import json
import os
import sys

from dotenv import load_dotenv

from needle.shared.judge import judge_instructions, parse_judgement
from needle.shared.llm import OpenRouterClient

load_dotenv("/home/yallen/needle/.env")
items_glob, out_path = sys.argv[1], sys.argv[2]
items = []
for p in sorted(glob.glob(items_glob)):
    items += json.load(open(p))
done = json.load(open(out_path)) if os.path.exists(out_path) else {}
todo = [it for it in items if str(it["id"]) not in done]
print("items", len(items), "todo", len(todo), flush=True)
llm = OpenRouterClient(api_key=os.environ["OPENROUTER_API_KEY"], model="openai/gpt-6-luna")
system = judge_instructions()
sem = asyncio.Semaphore(8)


async def one(it):
    async with sem:
        text, err = await llm.complete(it["prompt"], max_tokens=65_536, reasoning_effort="high", system=system)
    if err:
        return str(it["id"]), {"error": err}
    j = parse_judgement(text)
    return str(it["id"]), {"rating": j.rating if j else None, "label": j.label if j else None, "raw": (text or "")[-400:]}


async def main():
    n = 0
    for coro in asyncio.as_completed([one(it) for it in todo]):
        k, rec = await coro
        done[k] = rec
        n += 1
        if n % 25 == 0:
            json.dump(done, open(out_path, "w"))
            print("progress", n, flush=True)
    json.dump(done, open(out_path, "w"))
    await llm.aclose()
    ok = sum(1 for r in done.values() if r.get("rating") is not None)
    print("rated", ok, "errors", len(done) - ok, flush=True)


asyncio.run(main())
