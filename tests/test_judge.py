from keenbench.shared.judge import (
    PARSE_RETRY_SUFFIX,
    QueryProfile,
    build_judge_prompt,
    build_user_message,
    classify_query,
    judge_one,
    parse_judgement,
    parse_query_profile,
)

PROFILE = QueryProfile(
    query_type="B",
    archetype="Ephemeral",
    dated_event=True,
    objective="find the score",
    core_aspects=("final score", "match date"),
)


class FakeLLM:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    async def complete(self, prompt, *, max_tokens, reasoning_effort):
        self.prompts.append(prompt)
        return self.replies.pop(0)


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
    j = parse_judgement("rating: 4\nlabel: FailsM\nreasoning: r")
    assert j.rating == 4 and j.label == "FailsM"


def test_parse_derives_label_when_invalid():
    j = parse_judgement("rating: 4\nlabel: Amazing\nreasoning: r")
    assert j.rating == 4 and j.label == "FullyM"


def test_parse_falls_back_to_json():
    j = parse_judgement('{\n\t"rating": 3,\n\t"label": "HM",\n\t"reasoning": "r"\n}')
    assert j is not None and j.rating == 3 and j.label == "HM"


def test_parse_falls_back_to_regex_scrape():
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
    assert "**Type A (Broad/Exploratory)**" in prompt
    assert "**Ephemeral**" in prompt


async def test_judge_one_success_and_llm_error():
    ok = FakeLLM(("rating: 3\nlabel: HM\nreasoning: r", None))
    j, err = await judge_one(ok, "q", url="https://e", today="2026-07-01")
    assert err is None and j.rating == 3

    errored = FakeLLM((None, {"error_type": "http_error", "error_message": "500"}))
    j, err = await judge_one(errored, "q", url="https://e", today="2026-07-01")
    assert j is None and err["error_type"] == "http_error"
    assert len(errored.prompts) == 1


async def test_judge_one_retries_parse_error_with_format_reminder():
    llm = FakeLLM(("i refuse to answer", None), ("rating: 2\nlabel: SM\nreasoning: r", None))
    j, err = await judge_one(llm, "q", url="https://e", today="2026-07-01")
    assert err is None and j.rating == 2
    assert llm.prompts[1] == llm.prompts[0] + PARSE_RETRY_SUFFIX


async def test_judge_one_gives_up_after_one_parse_retry():
    llm = FakeLLM(("i refuse to answer", None), ("still not yaml", None))
    j, err = await judge_one(llm, "q", url="https://e", today="2026-07-01")
    assert j is None and err["error_type"] == "judge_parse_error"
    assert err["error_message"] == "still not yaml"
    assert len(llm.prompts) == 2


def test_parse_query_profile():
    p = parse_query_profile(
        "objective: find the score\ncore_aspects:\n  - final score\n"
        "query_type: B\narchetype: Ephemeral\ndated_event: true"
    )
    assert p.query_type == "B"
    assert p.archetype == "Ephemeral"
    assert p.dated_event is True
    assert p.objective == "find the score"
    assert p.core_aspects == ("final score",)


def test_parse_query_profile_normalizes_variants():
    p = parse_query_profile(
        "query_type: b (Specific/Closed)\narchetype: EVERGREEN\ndated_event: 'no'"
    )
    assert p.query_type == "B"
    assert p.archetype == "Evergreen"
    assert p.dated_event is False
    assert p.objective == "" and p.core_aspects == ()

    p = parse_query_profile("query_type: Type C\narchetype: Ephemeral content\ndated_event: yes")
    assert p.query_type == "C"
    assert p.archetype == "Ephemeral"
    assert p.dated_event is True


def test_parse_query_profile_flattens_multiline_fields():
    p = parse_query_profile(
        "query_type: A\narchetype: Persistent\nobjective: |\n  line one\n  line two\n"
        'core_aspects:\n  - "multi\\nline  aspect"'
    )
    assert p.objective == "line one line two"
    assert p.core_aspects == ("multi line aspect",)


def test_parse_query_profile_rejects_invalid():
    assert parse_query_profile(None) is None
    assert parse_query_profile("") is None
    assert parse_query_profile("query_type: D\narchetype: Ephemeral") is None
    assert parse_query_profile("query_type: A\narchetype: Timeless") is None
    assert parse_query_profile("rating: 3\nlabel: HM") is None


def test_user_message_includes_profile_block():
    msg = build_user_message("who won", url="https://e", today="2026-07-01", profile=PROFILE)
    assert "**Query Analysis**" in msg
    assert "- Query type: B" in msg
    assert "- Content archetype: Ephemeral" in msg
    assert "- Specific dated current-event query: yes" in msg
    assert "- Objective: find the score" in msg
    assert "  - final score" in msg and "  - match date" in msg
    assert msg.index("**Query Analysis**") < msg.index("**Document to evaluate**")

    without = build_user_message("who won", url="https://e", today="2026-07-01")
    assert "**Query Analysis**" not in without


async def test_judge_one_passes_profile():
    llm = FakeLLM(("rating: 3\nlabel: HM\nreasoning: r", None))
    j, err = await judge_one(llm, "who won", url="https://e", today="2026-07-01", profile=PROFILE)
    assert err is None and j.rating == 3
    assert "- Query type: B" in llm.prompts[0]


async def test_classify_query_success_and_retry():
    llm = FakeLLM(
        ("not a profile", None),
        ("query_type: C\narchetype: Persistent\ndated_event: false\nobjective: o", None),
    )
    p, err = await classify_query(llm, "x vs y", today="2026-07-01")
    assert err is None and p.query_type == "C" and p.archetype == "Persistent"
    assert len(llm.prompts) == 2
    assert "**Query**: x vs y" in llm.prompts[0]
    assert "Today's date: 2026-07-01" in llm.prompts[0]
    assert "**Type A (Broad/Exploratory)**" in llm.prompts[0]
    assert "**Ephemeral**" in llm.prompts[0]


async def test_classify_query_returns_llm_error():
    llm = FakeLLM((None, {"error_type": "http_error", "error_message": "500"}))
    p, err = await classify_query(llm, "q", today="2026-07-01")
    assert p is None and err["error_type"] == "http_error"
