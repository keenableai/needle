import re
import urllib.request
from collections import Counter
from collections.abc import Callable, Iterable
from functools import lru_cache
from pathlib import Path

import fasttext
from huggingface_hub import hf_hub_download
from tokenizers import BertWordPieceTokenizer
from wordfreq import zipf_frequency

SUBWORD_THRESHOLD = 5
UNK = "[UNK]"
UNK_PIECES = 99
LID_URL = "https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.ftz"
FOREIGN_CONFIDENT = 0.7
ENGLISH_CONFIDENT = 0.5
ENGLISH_ZIPF = 3.0
ENGLISH_WORD_FRACTION = 0.6

NON_LATIN_RE = re.compile("[^\u0020-\u024f\u1e00-\u1eff\u2000-\u206f\u20a0-\u20cf]")
PUNCT_RE = re.compile(r"[^\w\s]")
VIN_CANDIDATE_RE = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b", re.IGNORECASE)
HEX_HASH_RE = re.compile(r"\b[0-9a-fA-F]{24,}\b")
HEX_ETH_ADDRESS_RE = re.compile(r"\b0[xX][0-9a-fA-F]{40}\b")
CRYPTO_BASE58_RE = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b")
URLISH_RE = re.compile(r"https?://|www\.|\.(com|org|net|io|de|fr|ru|jp)(\b|/)", re.I)

Tokenize = Callable[[str], list[str]]
Lid = Callable[[str], tuple[str, float]]


def _any_token(regex: re.Pattern, query: str, ok: Callable[[str], bool]) -> bool:
    return any(ok(m.group(0)) for m in regex.finditer(query))


def _contains_vin(query: str) -> bool:
    return _any_token(
        VIN_CANDIDATE_RE,
        query,
        lambda t: any(c.isalpha() for c in t) and any(c.isdigit() for c in t),
    )


def _contains_hex_hash(query: str) -> bool:
    return _any_token(HEX_HASH_RE, query, lambda t: any(c in "abcdefABCDEF" for c in t)) or bool(
        HEX_ETH_ADDRESS_RE.search(query)
    )


def _contains_crypto_address(query: str) -> bool:
    return _any_token(
        CRYPTO_BASE58_RE,
        query,
        lambda t: (
            any(c.isdigit() for c in t)
            and any(c.isupper() for c in t)
            and any(c.islower() for c in t)
        ),
    )


def is_eligible(query: str) -> bool:
    return not (
        NON_LATIN_RE.search(query)
        or _contains_vin(query)
        or _contains_hex_hash(query)
        or _contains_crypto_address(query)
    )


def words_for(query: str) -> list[str]:
    cleaned = PUNCT_RE.sub(" ", query.lower())
    return [w for w in cleaned.split() if w]


def hard_words_for(
    words: list[str], tokenize: Tokenize, subword_threshold: int = SUBWORD_THRESHOLD
) -> list[dict]:
    out = []
    for w in words:
        if not any(c.isalpha() for c in w):
            continue
        pieces = tokenize(w)
        if not pieces:
            continue
        if UNK in pieces or len(pieces) >= subword_threshold:
            out.append({"word": w, "subwords": list(pieces)})
    return out


def is_english(query: str, context_words: list[str], lid: Lid) -> bool:
    lang_full, p_full = lid(query)
    context = " ".join(context_words)
    lang_ctx, p_ctx = lid(context) if context else (lang_full, p_full)
    if lang_full != "en" and p_full >= FOREIGN_CONFIDENT:
        return False
    if lang_ctx != "en" and p_ctx >= FOREIGN_CONFIDENT:
        return False
    if lang_ctx == "en" and p_ctx >= ENGLISH_CONFIDENT:
        return True
    letter_words = [w for w in context_words if w.isalpha()]
    if not letter_words:
        return True
    common = sum(zipf_frequency(w, "en") >= ENGLISH_ZIPF for w in letter_words)
    return common / len(letter_words) >= ENGLISH_WORD_FRACTION


def length_bucket(n_words: int) -> str:
    if n_words <= 2:
        return "short"
    if n_words <= 5:
        return "medium"
    return "long"


def load_tokenizer(vocab_path: str | None = None) -> Tokenize:
    if vocab_path is None:
        vocab_path = hf_hub_download("bert-base-uncased", "vocab.txt")
    tokenizer = BertWordPieceTokenizer(vocab_path, lowercase=True)

    @lru_cache(maxsize=200_000)
    def encode(word: str) -> list[str]:
        return list(tokenizer.encode(word, add_special_tokens=False).tokens)

    return encode


def load_lid(model_path: str | None = None) -> Lid:
    if model_path is None:
        cached = Path.home() / ".cache" / "lid.176.ftz"
        if not cached.exists():
            cached.parent.mkdir(parents=True, exist_ok=True)
            urllib.request.urlretrieve(LID_URL, cached)
        model_path = str(cached)
    model = fasttext.load_model(model_path)

    def lid(text: str) -> tuple[str, float]:
        labels, probs = model.predict(text.lower().replace("\n", " "), k=1)
        return labels[0].removeprefix("__label__"), probs[0]

    return lid


def dedup_by_ngrams(
    rows: list[dict], n: int, max_per_gram: int, query_field: str = "query"
) -> list[dict]:
    counts: dict[tuple[str, ...], int] = {}
    kept = []
    for row in rows:
        words = words_for(row[query_field])
        grams = [tuple(words[i : i + n]) for i in range(len(words) - n + 1)] or [tuple(words)]
        if any(counts.get(g, 0) >= max_per_gram for g in grams):
            continue
        for g in grams:
            counts[g] = counts.get(g, 0) + 1
        kept.append(row)
    return kept


def filter_rows(
    rows: Iterable[dict],
    tokenize: Tokenize,
    lid: Lid | None,
    min_words: int = 3,
    max_query_len: int = 200,
    max_word_len: int = 40,
    subword_threshold: int = SUBWORD_THRESHOLD,
    dedup_ngram: int = 3,
    dedup_max: int = 2,
    query_field: str = "query",
) -> tuple[list[dict], dict[str, int]]:
    stats: Counter[str] = Counter()

    kept = []
    for row in rows:
        query = (row.get(query_field) or "").strip()
        if not query or len(query) > max_query_len:
            stats["bad_length"] += 1
            continue
        if URLISH_RE.search(query):
            stats["urlish"] += 1
            continue
        words = words_for(query)
        if len(words) < min_words:
            stats["too_few_words"] += 1
            continue
        if max((len(w) for w in words), default=0) > max_word_len:
            stats["long_word"] += 1
            continue
        if not is_eligible(query):
            stats["ineligible"] += 1
            continue
        hard = hard_words_for(words, tokenize, subword_threshold)
        if not hard:
            stats["no_rare_word"] += 1
            continue
        if lid is not None:
            hard_set = {h["word"] for h in hard}
            context_words = [w for w in words if w not in hard_set]
            if not is_english(query, context_words, lid):
                stats["non_english"] += 1
                continue
        kept.append(
            {
                **row,
                "length_bucket": length_bucket(len(words)),
                "n_words": len(words),
                "hard_words": hard,
                "max_pieces": max(
                    UNK_PIECES if UNK in h["subwords"] else len(h["subwords"]) for h in hard
                ),
            }
        )
    if dedup_ngram:
        kept.sort(key=lambda r: -r["max_pieces"])
        before = len(kept)
        kept = dedup_by_ngrams(kept, dedup_ngram, dedup_max, query_field)
        stats["ngram_dup"] = before - len(kept)
    kept.sort(key=lambda r: (r["length_bucket"], -r["max_pieces"]))
    return kept, stats
