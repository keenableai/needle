import asyncio
import json
import os
import sys

from dotenv import load_dotenv

from needle.shared.judge import PARSE_RETRY_SUFFIX, QueryProfile, build_judge_input, judge_instructions, parse_judgement
from needle.shared.llm import LLMClientError, OpenRouterClient

load_dotenv()
items_path, model, effort, out_path = sys.argv[1:5]
limit = int(sys.argv[5]) if len(sys.argv) > 5 else None
items = json.load(open(items_path))[:limit]
done = json.load(open(out_path)) if os.path.exists(out_path) else {}
todo = [it for it in items if done.get(str(it["id"]), {}).get("rating") is None]
print("items", len(items), "todo", len(todo), model, effort, flush=True)
llm = OpenRouterClient(api_key=os.environ["OPENROUTER_API_KEY"], model=model)
system = judge_instructions()
sem = asyncio.Semaphore(8)


async def one(it):
    profile = QueryProfile(**{k: tuple(v) if isinstance(v, list) else v for k, v in it["query_profile"].items()})
    prompt = build_judge_input(it["query"], url=it["url"], title=it["title"], content=it["snippet"], today=it["today"], profile=profile)
    rec = {"rating": None, "cost": 0.0, "prompt_tokens": 0, "completion_tokens": 0}
    for attempt in (prompt, prompt + PARSE_RETRY_SUFFIX):
        body = {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": attempt}], "max_tokens": 65_536, "temperature": 0.0, "reasoning": {"effort": effort}, "usage": {"include": True}}
        try:
            async with sem:
                payload = await llm._request(body)
        except LLMClientError as exc:
            rec["error"] = str(exc)[:300]
            break
        usage = payload.get("usage") or {}
        rec["cost"] += usage.get("cost") or 0.0
        rec["prompt_tokens"] += usage.get("prompt_tokens") or 0
        rec["completion_tokens"] += usage.get("completion_tokens") or 0
        j = parse_judgement(payload["choices"][0]["message"].get("content"))
        if j:
            rec.update(rating=j.rating, label=j.label, reasoning=j.reasoning[:400])
            break
    return str(it["id"]), rec


async def main():
    n = 0
    for coro in asyncio.as_completed([one(it) for it in todo]):
        k, rec = await coro
        done[k] = rec
        n += 1
        if n % 50 == 0:
            json.dump(done, open(out_path, "w"))
            print("progress", n, "cost", round(sum(r["cost"] for r in done.values()), 2), flush=True)
    json.dump(done, open(out_path, "w"))
    await llm.aclose()
    ok = [r for r in done.values() if r["rating"] is not None]
    print("rated", len(ok), "errors", len(done) - len(ok), "cost", round(sum(r["cost"] for r in done.values()), 3), "tokens/item", sum(r["prompt_tokens"] for r in done.values()) // max(1, len(done)), sum(r["completion_tokens"] for r in done.values()) // max(1, len(done)), flush=True)


asyncio.run(main())
