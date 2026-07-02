from keenbench.scholar.projection import (
    body_query_ok,
    clean_body_query,
    content_tokens,
    degrade_title,
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
    assert clean_body_query('  "quantized llama throughput"  ') == "quantized llama throughput"
    assert clean_body_query("NO_DISTINCT_QUERY") is None
    assert clean_body_query("  no_distinct_query  ") is None
    assert clean_body_query("") is None
    assert clean_body_query(None) is None


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
