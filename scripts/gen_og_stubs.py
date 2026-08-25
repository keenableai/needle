import html
import re
import struct
import sys
from pathlib import Path

BASE = "https://keenableai.github.io/needle/"
SITE_TITLE = "NEEDLE — search engine benchmarks"
TITLE_SUFFIX = " | NEEDLE search benchmark"
BLURB = ("NEEDLE is a live open-source benchmark that compares public "
         "search APIs on news, finance, scholar, rare-word, and legal "
         "queries.")

VERTICALS = {"news": "News", "finance": "Finance", "scholar": "Scholar",
             "agentic_rare": "AgenticRare", "legal": "Legal"}

SECTION_DESCRIPTIONS = {
    "sec-results": "Standings and 7-day leaderboards for every vertical.",
    "sec-trends": "Per-engine quality over time for this slice.",
    "sec-price": "7-day search quality against public price per 1,000 "
                 "queries.",
    "sec-latency": "p50-to-p95 search latency per engine over the last "
                   "7 days.",
    "sec-overlap": "How independent each engine's index is: shared "
                   "results, borrowing, and uniqueness.",
    "sec-appendix": "Methodology: query generation, metrics, judging, "
                    "and engine configuration.",
}

SECTION_IMAGES = {
    "top": "card-standings",
    "sec-results": "card-standings",
    "sec-trends": "card-trends",
    "sec-price": "card-quality-price",
    "sec-latency": "card-latency-dumbbell",
    "sec-overlap": "card-independence",
}

STUB = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="robots" content="noindex">
<title>{title}</title>
<meta property="og:type" content="website">
<meta property="og:site_name" content="NEEDLE">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<meta property="og:url" content="{url}">
{image}<meta name="twitter:card" content="{card}">
<meta http-equiv="refresh" content="0; url=../#{anchor}">
</head>
<body>
<p><a href="../#{anchor}">Continue to {title}</a></p>
<script>location.replace("../#{anchor}");</script>
</body>
</html>
"""


def heading_in(doc, start):
    depth = 0
    for m in re.finditer(r"<h2[^>]*>(.*?)</h2>|<div\b|</div>",
                         doc[start:start + 20000], re.S):
        if m.group().startswith("<h2"):
            return html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()
        depth += 1 if m.group().startswith("<div") else -1
        if depth == 0:
            return None
    return None


def main():
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    doc = src.read_text()
    doc = re.sub(r'<span class="vert" data-vert="([a-z_]+)"></span>',
                 lambda m: VERTICALS.get(m.group(1), m.group(1)), doc)

    sections = [(m.start(), m.group(1), html.unescape(m.group(2)))
                for m in re.finditer(
                    r'<h2 class="section-title" id="([^"]+)">(.*?)</h2>',
                    doc)]

    anchors = [("top", 0, SITE_TITLE)]
    anchors += [(sid, pos, f"{text}{TITLE_SUFFIX}") for pos, sid, text in sections]
    for m in re.finditer(r'<div class="(?:lb-panel[^"]*|card)" id="([^"]+)"',
                         doc):
        heading = heading_in(doc, m.start())
        if heading:
            anchors.append((m.group(1), m.start(), f"{heading}{TITLE_SUFFIX}"))

    def section_for(pos):
        sid = "top"
        for s_pos, s_id, _ in sections:
            if s_pos <= pos:
                sid = s_id
        return sid

    written = 0
    for anchor, pos, title in anchors:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", anchor):
            print(f"skip unsafe anchor id {anchor!r}", file=sys.stderr)
            continue
        image, card = "", "summary"
        img_name = SECTION_IMAGES.get(anchor, anchor)
        png = out / "og" / f"{img_name}.png"
        if png.is_file():
            w, h = struct.unpack(">II", png.read_bytes()[16:24])
            image = (f'<meta property="og:image" content="{BASE}og/{img_name}.png">\n'
                     f'<meta property="og:image:width" content="{w}">\n'
                     f'<meta property="og:image:height" content="{h}">\n')
            card = "summary_large_image"
        stub_dir = out / anchor
        stub_dir.mkdir(parents=True, exist_ok=True)
        slice_desc = SECTION_DESCRIPTIONS.get(section_for(pos), "")
        desc = f"{slice_desc} {BLURB}".strip()
        (stub_dir / "index.html").write_text(STUB.format(
            title=html.escape(title),
            description=html.escape(desc),
            url=f"{BASE}{anchor}/",
            anchor=anchor,
            image=image,
            card=card))
        written += 1
    print(f"wrote {written} stubs to {out}")


if __name__ == "__main__":
    main()
