from keenbench.shared.judge import (
    build_judge_prompt,
    build_user_message,
    judge_one,
    parse_judgement,
)


class FakeLLM:
    def __init__(self, reply):
        self.reply = reply
        self.prompt = None

    async def complete(self, prompt, *, max_tokens, reasoning_effort):
        self.prompt = prompt
        return self.reply


def test_parse_plain_yaml():
    j = parse_judgement("rating: 3\nlabel: HM\nreasoning: good coverage")
    assert j.rating == 3 and j.label == "HM" and j.reasoning == "good coverage"


def test_parse_fenced_yaml():
    j = parse_judgement('```yaml\nrating: 4\nlabel: FullyM\nreasoning: "one stop"\n```')
    assert j.rating == 4 and j.label == "FullyM"


def test_parse_json_fence_and_unclosed_fence():
    j = parse_judgement("```json\nrating: 3\nlabel: HM\nreasoning: r\n```")
    assert j.rating == 3
    j2 = parse_judgement("```yaml\nrating: 4\nlabel: FullyM\nreasoning: r")
    assert j2 is not None and j2.rating == 4


def test_parse_derives_label_when_missing():
    j = parse_judgement("rating: 2\nreasoning: partial")
    assert j.rating == 2 and j.label == "SM"


def test_parse_rejects_out_of_range_or_garbage():
    assert parse_judgement("rating: 9\nlabel: HM") is None
    assert parse_judgement("not yaml: [") is None
    assert parse_judgement("") is None
    assert parse_judgement("reasoning: no rating here") is None


def test_parse_keeps_model_label_even_when_mismatched():
    # Parity with keenable-eval: a mismatch is the judge's signal, not ours to hide.
    j = parse_judgement("rating: 4\nlabel: FailsM\nreasoning: r")
    assert j.rating == 4 and j.label == "FailsM"


def test_parse_derives_label_when_invalid():
    j = parse_judgement("rating: 4\nlabel: Amazing\nreasoning: r")
    assert j.rating == 4 and j.label == "FullyM"


def test_parse_falls_back_to_json():
    # Tab-indented JSON is invalid YAML but valid JSON.
    j = parse_judgement('{\n\t"rating": 3,\n\t"label": "HM",\n\t"reasoning": "r"\n}')
    assert j is not None and j.rating == 3 and j.label == "HM"


def test_parse_falls_back_to_regex_scrape():
    # Unquoted nested colons break YAML; the field scrape still recovers it.
    j = parse_judgement("rating: 3\nlabel: HM\nreasoning: broken: nested: colons")
    assert j is not None and j.rating == 3 and j.label == "HM"
    assert "broken: nested: colons" in j.reasoning


def test_parse_rejects_non_integer_ratings():
    assert parse_judgement("rating: true\nlabel: HM") is None
    assert parse_judgement("rating: 3.7\nlabel: HM") is None
    j = parse_judgement('rating: "3"\nreasoning: r')
    assert j is not None and j.rating == 3 and j.label == "HM"


def test_build_user_message_and_content_cap():
    msg = build_user_message(
        "mayor of austin",
        url="https://ex.com",
        title="T",
        published="2026-07-01",
        content="x" * 100,
        today="2026-07-01",
        max_content_chars=10,
    )
    assert "**Query**: mayor of austin" in msg
    assert "- Published: 2026-07-01" in msg
    assert "characters) not shown" in msg


def test_build_judge_prompt_includes_system_rules():
    prompt = build_judge_prompt("q", url="https://e", today="2026-07-01")
    assert "Needs Met rating framework" in prompt
    assert "**Query**: q" in prompt


async def test_judge_one_success_and_parse_error():
    ok = FakeLLM(("rating: 3\nlabel: HM\nreasoning: r", None))
    j, err = await judge_one(ok, "q", url="https://e", today="2026-07-01")
    assert err is None and j.rating == 3

    bad = FakeLLM(("i refuse to answer", None))
    j, err = await judge_one(bad, "q", url="https://e", today="2026-07-01")
    assert j is None and err["error_type"] == "judge_parse_error"

    errored = FakeLLM((None, {"error_type": "http_error", "error_message": "500"}))
    j, err = await judge_one(errored, "q", url="https://e", today="2026-07-01")
    assert j is None and err["error_type"] == "http_error"
