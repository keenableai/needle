import json
import math
import re
from collections import Counter
from functools import cache

import snowballstemmer

from needle.coding.models import doc_key
from needle.coding.projection import CAMEL_RE

BM25_K1 = 1.2
BM25_B = 0.75
TERM_RE = re.compile(r"[a-z0-9]+")
LLMS_FULL_PAGE_RE = re.compile(r"^# .*\nSource: (\S+)$", re.M)
JS_BARE_KEY_RE = re.compile(r'"(?:[^"\\]|\\.)*"|(?<=[{,])([A-Za-z_$][\w$]*)(?=:)')
STEMMER = snowballstemmer.stemmer("english")

Corpus = dict[str, Counter[str]]


@cache
def stem(word: str) -> str:
    return STEMMER.stemWord(word)


def terms(text: str) -> Counter[str]:
    return Counter(stem(w) for w in TERM_RE.findall(CAMEL_RE.sub(" ", text).lower()))


def page_key(url: str) -> str:
    return doc_key(url) or url


def bm25(query: str, corpus: Corpus) -> dict[str, float]:
    wanted = set(terms(query))
    n = len(corpus)
    avg = sum(page.total() for page in corpus.values()) / n or 1.0
    df = Counter(t for page in corpus.values() for t in wanted & page.keys())
    idf = {t: math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5)) for t in wanted}

    def score(page: Counter[str]) -> float:
        norm = BM25_K1 * (1 - BM25_B + BM25_B * page.total() / avg)
        return sum(idf[t] * page[t] * (BM25_K1 + 1) / (page[t] + norm) for t in wanted if page[t])

    return {key: score(page) for key, page in corpus.items()}


def ranks_first(query: str, corpus: Corpus, gold: str) -> bool:
    if gold not in corpus:
        return False
    scores = bm25(query, corpus)
    best = scores.pop(gold)
    return all(best > s for s in scores.values())


def sphinx_corpus(js: str, site: str) -> Corpus:
    try:
        literal = js[js.index("(") + 1 : js.rindex(")")]
        index = json.loads(JS_BARE_KEY_RE.sub(_quote_bare_key, literal))
        names = index.get("docnames") or index["filenames"]
        pages: list[Counter[str]] = [Counter() for _ in names]
        for field in ("terms", "titleterms"):
            for term, where in index.get(field, {}).items():
                for i in where if isinstance(where, list) else (where,):
                    pages[i][term] = 1
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        return {}
    return {page_key(f"{site}{name}.html"): page for name, page in zip(names, pages, strict=True)}


def _quote_bare_key(m: re.Match[str]) -> str:
    return f'"{m.group(1)}"' if m.group(1) else m.group(0)


def llms_full_corpus(text: str) -> Corpus:
    heads = list(LLMS_FULL_PAGE_RE.finditer(text))
    ends = [m.start() for m in heads[1:]] + [len(text)]
    return {
        page_key(m.group(1)): terms(text[m.start() : end])
        for m, end in zip(heads, ends, strict=False)
    }
