from keenbench.scholar.projection import (
    body_has_bad_anchor,
    body_query_ok,
    clean_body_query,
    content_tokens,
    degrade_title,
    title_is_specific,
)


def test_title_is_specific():
    # generic short titles: no distinctive token, too few content words
    assert not title_is_specific("Temperature Measurement in Agent Systems")
    assert not title_is_specific("A Study of Neural Networks")
    # acronyms / coined names / digits / camelcase keep it
    assert title_is_specific("VT-WAM: Visual-Tactile World Action Model")
    assert title_is_specific("WorldDirector Building Controllable World Simulators")
    assert title_is_specific("DNABERT-2 for 5500 bp Sequences")
    assert title_is_specific("PointDiT Pixel-Space Diffusion")
    # hyphenated compound coinages are distinctive even in title case
    assert title_is_specific("A Cap-Axis Integral Diagnostic of Factor Models")
    assert title_is_specific("Mixture-Preserving Interpolation for Volatility Models")
    # long descriptive titles pass on content-word count alone
    assert title_is_specific(
        "association between systemic inflammation indices and recurrence risk "
        "in primary budd chiari syndrome"
    )


def test_degrade_title():
    assert (
        degrade_title("SmoothQuant: Accurate and Efficient Quantization")
        == "smoothquant accurate and efficient quantization"
    )
    assert degrade_title("Attention Is All You Need") == "attention is all you need"


def test_degrade_title_strips_latex_and_punctuation():
    out = degrade_title(r"On $\mathcal{O}(n)$ Bounds for Sparse-Graph Coloring")
    assert "$" not in out
    assert "mathcal" not in out
    assert "sparse-graph" in out


def test_degrade_title_too_short():
    assert degrade_title("GPT-5") is None
    assert degrade_title("A Survey") is None


def test_clean_body_query():
    assert clean_body_query("smoothquant 8bit activation outliers\nextra line") == (
        "smoothquant 8bit activation outliers"
    )
    # whole-answer wrapping is unwrapped
    assert clean_body_query('  "quantized llama throughput"  ') == "quantized llama throughput"
    assert clean_body_query("NO_DISTINCT_QUERY") is None
    assert clean_body_query("  no_distinct_query  ") is None
    assert clean_body_query("") is None
    assert clean_body_query(None) is None


def test_clean_body_query_preserves_balanced_span_quotes():
    # a leading quoted span stays balanced (the reported unbalanced-quote bug)
    q = '"relational database that assists parsing" social hierarchies'
    assert clean_body_query(q) == q
    assert clean_body_query('foo "middle span" bar') == 'foo "middle span" bar'


def test_clean_body_query_drops_unbalanced_quotes():
    assert clean_body_query('relational database parsing" social hierarchies') == (
        "relational database parsing social hierarchies"
    )


def test_content_tokens_drops_stopwords_and_short():
    tokens = content_tokens("We study a novel Sparse quantization of transformers in llms")
    assert "sparse" in tokens
    assert "quantization" in tokens
    assert "transformers" in tokens
    assert "we" not in tokens
    assert "novel" not in tokens
    assert "study" not in tokens
    assert "in" not in tokens


def test_body_query_ok_requires_novel_tokens():
    title = "SmoothQuant: Accurate Quantization for Language Models"
    abstract = "We propose smoothquant, a quantization method for large language models."
    assert body_query_ok(
        "per-channel activation scaling 0.5 migration factor",
        title=title,
        abstract=abstract,
    )


def test_body_query_ok_rejects_metadata_leak():
    title = "SmoothQuant: Accurate Quantization for Language Models"
    abstract = "We propose smoothquant, a quantization method for large language models."
    assert not body_query_ok("smoothquant quantization language", title=title, abstract=abstract)


def test_body_query_ok_rejects_too_short():
    assert not body_query_ok("cohorts", title="T", abstract="A")
    assert not body_query_ok("the and of", title="T", abstract="A")


def test_body_has_bad_anchor():
    assert body_has_bad_anchor("Johnstone et al coronal temperature")
    assert body_has_bad_anchor("Schur complement bisection Theorem 7.2")
    assert body_has_bad_anchor("Supplementary Table 3 benchmark properties")
    assert body_has_bad_anchor("classification accuracy Figure 2 curves")
    # distinctive paper-own anchors with numbers are not bad anchors
    assert not body_has_bad_anchor("carvacrol 80.43 percent GC-MS")
    assert not body_has_bad_anchor("Ross 308 broilers cohort")
