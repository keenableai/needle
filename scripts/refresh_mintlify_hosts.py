import csv
import io
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import fire

OUT = Path(__file__).resolve().parents[1] / "src/needle/coding/data/mintlify_hosts.csv"
QUERY = """
SELECT NET.HOST(page) AS host, MIN(rank) AS rank
FROM `httparchive.crawl.requests`
WHERE date = @date AND type = 'font'
  AND (url LIKE '%/_mintlify/%' OR url LIKE '%mintcdn.com%' OR url LIKE '%mintlify-assets%')
GROUP BY host
ORDER BY rank, host
"""


def refresh(date: str = "", out: str = str(OUT)) -> None:
    crawl = date or datetime.now(UTC).strftime("%Y-%m-01")
    result = subprocess.run(
        [
            "bq",
            "query",
            "--use_legacy_sql=false",
            "--format=csv",
            "--max_rows=1000000",
            f"--parameter=date:DATE:{crawl}",
            QUERY,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    rows = [r for r in csv.DictReader(io.StringIO(result.stdout)) if r.get("host")]
    if not rows:
        raise SystemExit(f"error: no Mintlify hosts for crawl {crawl}; is the crawl published?")
    Path(out).write_text("".join(f"{r['host'].lower()},{r['rank']}\n" for r in rows))
    print(f"{len(rows)} hosts from crawl {crawl} -> {out}")


if __name__ == "__main__":
    fire.Fire(refresh)
