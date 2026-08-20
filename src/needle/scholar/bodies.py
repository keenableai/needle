from html.parser import HTMLParser
from xml.etree.ElementTree import ParseError

import defusedxml.ElementTree as ET
from defusedxml.common import DefusedXmlException

SKIP_TAGS = {"math", "script", "style", "svg", "noscript", "annotation", "annotation-xml"}
CAPTURE_TAGS = {"p", "figcaption"}


class _HtmlBlockExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._article = 0
        self._capture = 0
        self._skip = 0
        self._parts: list[str] = []
        self.blocks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "article":
            self._article += 1
        elif tag in SKIP_TAGS:
            self._skip += 1
        elif tag in CAPTURE_TAGS and self._article and not self._skip:
            self._capture += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "article":
            self._article = max(0, self._article - 1)
        elif tag in SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
        elif tag in CAPTURE_TAGS and self._capture:
            self._capture -= 1
            if not self._capture:
                block = " ".join(" ".join(self._parts).split())
                self._parts = []
                if block:
                    self.blocks.append(block)

    def handle_data(self, data: str) -> None:
        if self._capture and not self._skip:
            self._parts.append(data)


def html_body_text(html: str) -> str:
    extractor = _HtmlBlockExtractor()
    extractor.feed(html)
    extractor.close()
    return "\n".join(extractor.blocks)


def jats_body_text(xml: str) -> str:
    try:
        root = ET.fromstring(xml)
    except (ParseError, DefusedXmlException, ValueError):
        return ""
    body = root.find(".//body")
    if body is None:
        return ""
    blocks = []
    for p in body.findall(".//p"):
        text = " ".join("".join(p.itertext()).split())
        if text:
            blocks.append(text)
    return "\n".join(blocks)
