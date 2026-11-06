import hashlib
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
    for name in (
        "robots.txt",
        "sitemap.xml",
        "llms.txt",
        "llms-full.txt",
        "skill.md",
        ".nojekyll",
        "index.md",
    ):
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
    md_pages = (
        "index.md",
        "compare.md",
        "news.md",
        "finance.md",
        "scholar.md",
        "legal.md",
        "methodology.md",
        "skill.md",
    )
    for path in md_pages:
        url = f"https://keenableai.github.io/needle/{path}"
        assert url in sitemap, url
        assert url in llms, url
    assert llms.lstrip().startswith("# NEEDLE")
    assert re.search(r"^> ", llms, re.M)
    assert "https://keenableai.github.io/needle/llms.txt" in sitemap
    assert "https://keenableai.github.io/needle/llms-full.txt" in sitemap
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


LD_RE = re.compile(r'<script type="application/ld\+json">\s*(.*?)\s*</script>', re.S)
BASE = "https://keenableai.github.io/needle/"
DOI = "https://doi.org/10.5281/zenodo.22095155"
HISTORY = f"{BASE}data/history.jsonl"
CATALOG = f"{BASE}data/catalog.json"
SCORE_KEYS = {"mean_ndcg", "recall_at_k", "mrr_at_k", "ndcg", "recall"}

EXPECTED_TYPES = {
    "index": {
        "WebSite",
        "Dataset",
        "FAQPage",
        "Organization",
        "Question",
        "Answer",
        "DataDownload",
    },
    "compare": {
        "WebPage",
        "WebSite",
        "BreadcrumbList",
        "ListItem",
        "FAQPage",
        "Question",
        "Answer",
    },
    "methodology": {
        "HowTo",
        "HowToStep",
        "BreadcrumbList",
        "ListItem",
        "FAQPage",
        "Question",
        "Answer",
    },
    "news": {"Dataset", "Organization", "DataDownload", "BreadcrumbList", "ListItem"},
    "finance": {"Dataset", "Organization", "DataDownload", "BreadcrumbList", "ListItem"},
    "scholar": {"Dataset", "Organization", "DataDownload", "BreadcrumbList", "ListItem"},
    "legal": {"Dataset", "Organization", "DataDownload", "BreadcrumbList", "ListItem"},
}

INDEX_FAQ = {
    "What problem does NEEDLE solve?",
    "How often does NEEDLE run?",
    "Which metrics does NEEDLE report?",
    "How should I cite NEEDLE?",
}
COMPARE_FAQ = {
    "How does NEEDLE compare two search APIs?",
    "Which metrics does the comparison use?",
}
METHOD_FAQ = {
    "Does NEEDLE fetch landing pages?",
    "Can a provider overfit NEEDLE?",
}


def _ld_blocks(doc: str) -> list[object]:
    blocks = [json.loads(m.group(1)) for m in LD_RE.finditer(doc)]
    assert blocks, "missing JSON-LD"
    return blocks


def _collect(obj, types: set[str], nodes: dict[str, list]) -> None:
    if isinstance(obj, dict):
        typ = obj.get("@type")
        if isinstance(typ, str):
            types.add(typ)
            nodes.setdefault(typ, []).append(obj)
        elif isinstance(typ, list):
            for t in typ:
                types.add(t)
                nodes.setdefault(t, []).append(obj)
        for v in obj.values():
            _collect(v, types, nodes)
    elif isinstance(obj, list):
        for v in obj:
            _collect(v, types, nodes)


def _walk_keys(obj, keys: set[str]) -> None:
    if isinstance(obj, dict):
        keys.update(obj)
        for v in obj.values():
            _walk_keys(v, keys)
    elif isinstance(obj, list):
        for v in obj:
            _walk_keys(v, keys)


def test_jsonld_is_valid_and_typed():
    for key, path in PAGES.items():
        doc = path.read_text(encoding="utf-8")
        types: set[str] = set()
        nodes: dict[str, list] = {}
        for block in _ld_blocks(doc):
            assert isinstance(block, dict)
            assert block.get("@context") == "https://schema.org"
            _collect(block, types, nodes)
        missing = EXPECTED_TYPES[key] - types
        assert not missing, f"{key}: missing @type {missing}"


def test_jsonld_home_dataset_and_faq():
    types: set[str] = set()
    nodes: dict[str, list] = {}
    for block in _ld_blocks(PAGES["index"].read_text(encoding="utf-8")):
        _collect(block, types, nodes)
    site = nodes["WebSite"][0]
    assert site["name"] == "NEEDLE"
    assert site["url"] == BASE
    dataset = nodes["Dataset"][0]
    assert dataset["url"] == BASE
    assert dataset["identifier"] == DOI
    downloads = {d["contentUrl"] for d in dataset["distribution"]}
    assert downloads == {HISTORY, CATALOG}
    questions = {q["name"] for q in nodes["FAQPage"][0]["mainEntity"]}
    assert questions == INDEX_FAQ
    for q in nodes["Question"]:
        assert q["acceptedAnswer"]["text"].strip()


def test_jsonld_compare_and_methodology():
    types: set[str] = set()
    nodes: dict[str, list] = {}
    for block in _ld_blocks(PAGES["compare"].read_text(encoding="utf-8")):
        _collect(block, types, nodes)
    page = nodes["WebPage"][0]
    assert page["url"] == f"{BASE}compare/"
    crumbs = [i["item"] for i in nodes["BreadcrumbList"][0]["itemListElement"]]
    assert crumbs == [BASE, f"{BASE}compare/"]
    assert {q["name"] for q in nodes["FAQPage"][0]["mainEntity"]} == COMPARE_FAQ

    types = set()
    nodes = {}
    for block in _ld_blocks(PAGES["methodology"].read_text(encoding="utf-8")):
        _collect(block, types, nodes)
    howto = nodes["HowTo"][0]
    assert len(howto["step"]) == 4
    assert {q["name"] for q in nodes["FAQPage"][0]["mainEntity"]} == METHOD_FAQ
    crumbs = [i["item"] for i in nodes["BreadcrumbList"][0]["itemListElement"]]
    assert crumbs == [BASE, f"{BASE}methodology/"]


def test_jsonld_vertical_datasets_point_at_latest_files():
    for bench in ("news", "finance", "scholar", "legal"):
        types: set[str] = set()
        nodes: dict[str, list] = {}
        for block in _ld_blocks(PAGES[bench].read_text(encoding="utf-8")):
            _collect(block, types, nodes)
        dataset = nodes["Dataset"][0]
        assert dataset["url"] == f"{BASE}{bench}/"
        assert f"NEEDLE {bench}" in dataset["name"]
        downloads = {d["contentUrl"] for d in dataset["distribution"]}
        assert downloads == {HISTORY, f"{BASE}data/latest_{bench}.json"}
        crumbs = [i["item"] for i in nodes["BreadcrumbList"][0]["itemListElement"]]
        assert crumbs == [BASE, f"{BASE}{bench}/"]


def test_jsonld_does_not_embed_live_scores():
    keys: set[str] = set()
    for path in PAGES.values():
        for block in _ld_blocks(path.read_text(encoding="utf-8")):
            _walk_keys(block, keys)
    assert not (keys & SCORE_KEYS)


def test_dashboard_still_reads_rankeval_result_fields():
    src = (DASH / "index.html").read_text(encoding="utf-8")
    for field in ("title", "url", "snippet", "rating", "penalized", "label", "reasoning", "gates"):
        assert f"r.{field}" in src, field


MD_PAGES = {
    "index": DASH / "index.md",
    "compare": DASH / "compare.md",
    "methodology": DASH / "methodology.md",
    "news": DASH / "news.md",
    "finance": DASH / "finance.md",
    "scholar": DASH / "scholar.md",
    "legal": DASH / "legal.md",
}

DIR_MD = {
    "compare": DASH / "compare" / "index.md",
    "methodology": DASH / "methodology" / "index.md",
    "news": DASH / "news" / "index.md",
    "finance": DASH / "finance" / "index.md",
    "scholar": DASH / "scholar" / "index.md",
    "legal": DASH / "legal" / "index.md",
}

DIRECTIVE_RE = re.compile(
    r'<div class="llms-directive">[\s\S]*?<a href="[^"]*llms\.txt">llms\.txt</a>',
)
DISPLAY_NONE_RE = re.compile(r"display\s*:\s*none", re.I)


def test_html_pages_have_llms_directive_near_body_top():
    for key, path in PAGES.items():
        doc = path.read_text(encoding="utf-8")
        body = doc.split("<body>", 1)[1]
        head = body[:2000]
        assert DIRECTIVE_RE.search(head), key
        before_nav = body.split("<nav", 1)[0]
        assert "llms-directive" in before_nav, key
        directive = re.search(r'<div class="llms-directive">[\s\S]*?</div>', body)
        assert directive, key
        assert not DISPLAY_NONE_RE.search(directive.group(0))
        assert ".md" in directive.group(0)


def test_llms_directive_css_is_clip_not_display_none():
    css = (DASH / "assets" / "needle.css").read_text(encoding="utf-8")
    block = re.search(r"\.llms-directive\s*\{([^}]+)\}", css)
    assert block
    rules = block.group(1)
    assert "clip:" in rules
    assert "display:none" not in rules.replace(" ", "")


def test_markdown_twins_exist_and_stay_small():
    for key, path in {**MD_PAGES, **DIR_MD}.items():
        text = path.read_text(encoding="utf-8")
        assert len(text) < 100_000, (key, len(text))
        assert text.lstrip().startswith("> ")
        assert "llms.txt" in text.split("\n", 3)[0]
        assert not re.search(r"function\s+\w+\s*\(", text)


def test_markdown_covers_html_faq_and_headings():
    home_md = MD_PAGES["index"].read_text(encoding="utf-8")
    home_html = PAGES["index"].read_text(encoding="utf-8")
    assert _h1(home_html) in home_md
    for q in INDEX_FAQ:
        assert q in home_html
        assert q in home_md
    assert "How to read the scoreboard" in home_html
    assert "How to read the scoreboard" in home_md
    assert "data-markdown-ignore" in home_html
    cmp_md = MD_PAGES["compare"].read_text(encoding="utf-8")
    cmp_html = PAGES["compare"].read_text(encoding="utf-8")
    assert _h1(cmp_html) in cmp_md
    for q in COMPARE_FAQ:
        assert q in cmp_html
        assert q in cmp_md
    method_md = MD_PAGES["methodology"].read_text(encoding="utf-8")
    method_html = PAGES["methodology"].read_text(encoding="utf-8")
    assert _h1(method_html) in method_md
    for q in METHOD_FAQ:
        assert q in method_html
        assert q in method_md


def test_skill_md_and_discovery():
    skill = (DASH / "skill.md").read_text(encoding="utf-8")
    assert skill.startswith("---\n")
    assert "name: needle" in skill
    assert "description:" in skill
    assert "license: MIT" in skill
    assert "do not invent" in skill.lower() or "Never invent" in skill
    assert "/mcp" in skill and "not an MCP" in skill
    copies = (
        DASH / ".well-known" / "skills" / "needle" / "SKILL.md",
        DASH / ".well-known" / "skills" / "default" / "skill.md",
        DASH / ".well-known" / "agent-skills" / "needle" / "SKILL.md",
    )
    raw = (DASH / "skill.md").read_bytes()
    for path in copies:
        assert path.read_bytes() == raw, path
    digest = hashlib.sha256(raw).hexdigest()
    agent = json.loads((DASH / ".well-known" / "agent-skills" / "index.json").read_text())
    assert agent["skills"][0]["name"] == "needle"
    assert agent["skills"][0]["digest"] == f"sha256:{digest}"
    skills = json.loads((DASH / ".well-known" / "skills" / "index.json").read_text())
    assert skills["skills"][0]["name"] == "needle"
    assert "https://keenableai.github.io/needle/skill.md" in (DASH / "sitemap.xml").read_text()


def test_llms_full_is_a_real_snapshot():
    text = (DASH / "llms-full.txt").read_text(encoding="utf-8")
    assert text.lstrip().startswith("# NEEDLE")
    for needle in (
        "methodology.md",
        "history.jsonl",
        "catalog.json",
        "compare.md",
        "10.5281/zenodo.22095155",
        "nDCG@5",
        "answer-recall@5",
    ):
        assert needle in text
    assert len(text) > 2000
    assert "not an MCP" in text
