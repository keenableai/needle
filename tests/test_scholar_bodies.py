from needle.scholar.bodies import html_body_text, jats_body_text

HTML = """
<html><head><title>Paper</title><style>p { color: red }</style></head>
<body>
<nav>arXiv menu text</nav>
<p>Content selection saved. Describe the issue below:</p>
<article>
<h1>A Title</h1>
<p>First   paragraph
with <span>inline</span> markup.</p>
<p>Uses <math><mi>x</mi><annotation>x equals y</annotation></math> notation.</p>
<figure>
  <svg><text>plot labels</text></svg>
  <figcaption>Figure 1: accuracy vs size.</figcaption>
</figure>
<script>var x = "not text";</script>
<p></p>
</article>
<p>Report issue footer widget.</p>
</body></html>
"""

JATS = """<?xml version="1.0"?>
<article>
  <front><abstract><p>Front abstract text.</p></abstract></front>
  <body>
    <sec>
      <title>Methods</title>
      <p>We   used
      a cohort of 40 mice.</p>
      <fig><caption><p>Figure 2: survival curves.</p></caption></fig>
    </sec>
  </body>
  <back><ref-list><mixed-citation>Some reference</mixed-citation></ref-list></back>
</article>
"""


def test_html_body_text():
    text = html_body_text(HTML)
    lines = text.split("\n")
    assert lines == [
        "First paragraph with inline markup.",
        "Uses notation.",
        "Figure 1: accuracy vs size.",
    ]


def test_html_body_text_empty():
    assert html_body_text("") == ""
    assert html_body_text("<body><p>outside any article</p></body>") == ""
    assert html_body_text("<article><div>no paragraphs</div></article>") == ""


def test_jats_body_text():
    text = jats_body_text(JATS)
    lines = text.split("\n")
    assert lines == [
        "We used a cohort of 40 mice.",
        "Figure 2: survival curves.",
    ]


def test_jats_body_text_bad_input():
    assert jats_body_text("not xml") == ""
    assert jats_body_text("<article><front><p>x</p></front></article>") == ""
