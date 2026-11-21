import argparse
import re
import shutil
import subprocess
import sys
import tarfile
from datetime import UTC, datetime
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
DASHBOARD = SCRIPTS.parent / "dashboard" / "index.html"
RENDER = SCRIPTS / "render_static_results.mjs"
TS_FMT = "%Y-%m-%dT%H:%MZ"
MONTH_RE = re.compile(r"\d{4}-(0[1-9]|1[0-2])")
BENCH_SUBJECT = re.compile(r"bench: (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z)")
FILES = {
    "results.csv": "needle-results-{month}.csv",
    "results.json": "needle-results-{month}.json",
    "results.md": "needle-results-{month}.md",
    "og/needle-overall.webp": "needle-overall-{month}.webp",
    "og/needle-overall.png": "needle-overall-{month}.png",
}


def month_end(month: str) -> datetime:
    if not MONTH_RE.fullmatch(month):
        raise SystemExit(f"month must be YYYY-MM, got {month!r}")
    year, mon = map(int, month.split("-"))
    return datetime(year + mon // 12, mon % 12 + 1, 1, tzinfo=UTC)


def snapshot_paths(history: Path, month: str) -> dict[str, Path]:
    return {src: history / name.format(month=month) for src, name in FILES.items()}


def existing(history: Path, month: str) -> list[Path]:
    return [p for p in snapshot_paths(history, month).values() if p.exists()]


def end_of_month_commit(log: list[tuple[str, str, str]], cutoff: str) -> str:
    state = log[0][0] if log else ""
    for _, parent, subject in log:
        m = BENCH_SUBJECT.fullmatch(subject)
        if not m:
            continue
        if m.group(1) < cutoff:
            return state
        state = parent
    raise SystemExit(f"no bench run before {cutoff} in the fetched gh-pages history; fetch deeper")


def git_log(site: Path) -> list[tuple[str, str, str]]:
    out = subprocess.run(
        ["git", "-C", str(site), "log", "--first-parent", "--format=%H%x09%P%x09%s"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    rows = []
    for line in out.splitlines():
        sha, parents, subject = line.split("\t", 2)
        rows.append((sha, parents.split(" ")[0], subject))
    return rows


def extract_data(site: Path, sha: str, out: Path) -> None:
    with subprocess.Popen(
        ["git", "-C", str(site), "archive", "--format=tar", sha, "data"], stdout=subprocess.PIPE
    ) as proc:
        assert proc.stdout
        with tarfile.open(fileobj=proc.stdout, mode="r|") as tar:
            tar.extractall(out, filter="data")
    if proc.returncode:
        raise SystemExit(f"git archive {sha} failed")


def build(site: str, out: str, month: str) -> None:
    cutoff = month_end(month)
    if cutoff > datetime.now(UTC):
        raise SystemExit(f"{month} is not over yet")
    site_dir, out_dir = Path(site), Path(out)
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True)
    if found := existing(site_dir / "history", month):
        print(f"{month} snapshot already exists ({found[0].name}), nothing to build")
        return
    sha = end_of_month_commit(git_log(site_dir), cutoff.strftime(TS_FMT))
    extract_data(site_dir, sha, out_dir)
    shutil.copyfile(DASHBOARD, out_dir / "index.html")
    subprocess.run(["node", str(RENDER), str(out_dir), cutoff.isoformat()], check=True)
    print(f"built {month} from gh-pages {sha[:8]}, clock at {cutoff.isoformat()}")


def store(site: str, out: str, month: str) -> None:
    history = Path(site) / "history"
    if found := existing(history, month):
        print(f"{month} snapshot already exists ({found[0].name}), left as is")
        return
    built = Path(out)
    missing = [src for src in FILES if not (built / src).is_file()]
    if missing:
        raise SystemExit(f"{month} snapshot build is missing {', '.join(missing)}")
    history.mkdir(parents=True, exist_ok=True)
    for src, dest in snapshot_paths(history, month).items():
        shutil.copyfile(built / src, dest)
        print(f"wrote {dest}")


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["build", "store"])
    parser.add_argument("--site", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--month", required=True)
    args = parser.parse_args(argv)
    {"build": build, "store": store}[args.command](args.site, args.out, args.month)


if __name__ == "__main__":
    main(sys.argv[1:])
