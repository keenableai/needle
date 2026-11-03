import html
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASH = ROOT / "dashboard"
PAGES = {
    "index": DASH / "index.html",
    "compare": DASH / "compare" / "index.html",
    "methodology": DASH / "methodology" / "index.html",
    "news": DASH / "news" / "index.html",
    "finance": DASH / "finance" / "index.html",
    "scholar": DASH / "scholar" / "index.html",
    "legal": DASH / "legal" / "index.html",
}


def _h1(doc: str) -> str:
    m = re.search(r"<h1[^>]*>(.*?)</h1>", doc, re.S)
    assert m, "missing h1"
    return re.sub(r"<[^>]+>", "", html.unescape(m.group(1))).strip()


def _title(doc: str) -> str:
    m = re.search(r"<title>(.*?)</title>", doc, re.S)
    assert m, "missing title"
    return html.unescape(m.group(1)).strip()


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_static_geo_files_exist():
    for name in ("robots.txt", "sitemap.xml", "llms.txt", "llms-full.txt"):
        assert (DASH / name).is_file(), name


def test_pages_have_unique_titles_and_h1s():
    titles = {}
    h1s = {}
    for key, path in PAGES.items():
        doc = path.read_text(encoding="utf-8")
        titles[key] = _title(doc)
        h1s[key] = _h1(doc)
        assert "NEEDLE" in titles[key] or "NEEDLE" in doc
        assert 'rel="canonical"' in doc
        assert "application/ld+json" in doc
        assert "og:title" in doc
        assert "twitter:title" in doc
    assert len(set(titles.values())) == len(titles), titles
    assert len(set(h1s.values())) == len(h1s), h1s
    assert "reviews cannot tell you" in h1s["index"]


def test_llms_and_sitemap_point_at_public_urls():
    llms = (DASH / "llms.txt").read_text(encoding="utf-8")
    sitemap = (DASH / "sitemap.xml").read_text(encoding="utf-8")
    pages = ("", "compare/", "news/", "finance/", "scholar/", "legal/", "methodology/")
    for path in pages:
        url = f"https://keenableai.github.io/needle/{path}"
        assert url in sitemap, url
        assert url.rstrip("/") in llms or url in llms
    assert "https://keenableai.github.io/needle/llms.txt" in sitemap
    assert "doi.org/10.5281/zenodo.22095155" in llms
    robots = (DASH / "robots.txt").read_text(encoding="utf-8")
    assert "Sitemap: https://keenableai.github.io/needle/sitemap.xml" in robots


def test_agents_md_points_at_data():
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "data/history.jsonl" in text
    assert "catalog.json" in text
    assert "compare/" in text


def test_gen_og_stubs_skips_reserved_dirs(tmp_path):
    mod = _load("gen_og_stubs", ROOT / "scripts" / "gen_og_stubs.py")
    src = tmp_path / "index.html"
    src.write_text(
        '<h2 class="section-title" id="news">News</h2>\n'
        '<h2 class="section-title" id="sec-results">Quality results</h2>\n',
        encoding="utf-8",
    )
    (tmp_path / "news").mkdir()
    (tmp_path / "news" / "index.html").write_text("keep", encoding="utf-8")
    sys.argv = ["gen_og_stubs.py", str(src), str(tmp_path)]
    mod.main()
    assert (tmp_path / "news" / "index.html").read_text(encoding="utf-8") == "keep"
    assert (tmp_path / "sec-results" / "index.html").is_file()


def test_publish_writes_catalog(tmp_path):
    mod = _load("publish_bench", ROOT / "scripts" / "publish_bench.py")
    mod.publish(site=str(tmp_path), runs_out=str(tmp_path / "runs"), ts="2026-08-17T00:00Z")
    catalog = json.loads((tmp_path / "data" / "catalog.json").read_text(encoding="utf-8"))
    assert catalog["name"] == "NEEDLE"
    assert catalog["benches"]["news"]["latest"] == "latest_news.json"
    assert catalog["updated"] == "2026-08-17T00:00Z"
