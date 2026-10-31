import asyncio
import json
import os
import sys
from urllib.parse import urlparse

from dotenv import load_dotenv

from needle.shared.search.ceramic import CeramicClient

load_dotenv("/home/yallen/needle/.env")
queries_path, out_path, n = sys.argv[1], sys.argv[2], int(sys.argv[3])
rows = [json.loads(l) for l in open(queries_path) if l.strip()]
site_rows = [r for r in rows if "site:" in r["query_text"]][:n]
client = CeramicClient(api_key=os.environ["CERAMIC_API_KEY"])


async def search(q):
    payload, err = await client._request_json("POST", f"{client.base_url}/search", json={"query": q}, headers={"Authorization": f"Bearer {client.api_key}"})
    if err:
        raise RuntimeError(err.get("error_message", str(err))[:120])
    res = payload.get("result", {}).get("results", []) if isinstance(payload, dict) else []
    return [x["url"] for x in res[:5] if x.get("url")]


def host_ok(u, host):
    h = urlparse(u).netloc.lower()
    return h == host or h.endswith("." + host)


async def main():
    out = []
    for r in site_rows:
        words = r["query_text"].split()
        host = next(w.split(":", 1)[1] for w in words if w.startswith("site:"))
        stripped = " ".join(w for w in words if not w.startswith("site:"))
        try:
            raw = await search(r["query_text"])
            strip = await search(stripped)
        except Exception as e:
            out.append({"query": r["query_text"], "error": str(e)[:120]})
            print("error", str(e)[:100], flush=True)
            continue
        rec = {"query": r["query_text"], "host": host, "raw": raw, "stripped": strip,
               "raw_host_share": sum(host_ok(u, host) for u in raw) / max(1, len(raw)),
               "stripped_host_share": sum(host_ok(u, host) for u in strip) / max(1, len(strip)),
               "overlap": len(set(raw) & set(strip)) / max(1, len(set(raw) | set(strip)))}
        out.append(rec)
        print(f"{host:22s} raw host-share {rec['raw_host_share']:.2f} ({len(raw)}) stripped {rec['stripped_host_share']:.2f} ({len(strip)}) jaccard {rec['overlap']:.2f}", flush=True)
    ok = [o for o in out if "error" not in o]
    if ok:
        print("mean host share raw %.2f stripped %.2f; mean jaccard %.2f; queries %d" % (sum(o["raw_host_share"] for o in ok) / len(ok), sum(o["stripped_host_share"] for o in ok) / len(ok), sum(o["overlap"] for o in ok) / len(ok), len(ok)))
    json.dump(out, open(out_path, "w"), indent=1)
    await client.aclose()


asyncio.run(main())
