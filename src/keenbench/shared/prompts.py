from functools import cache

from jinja2 import Environment, PackageLoader, StrictUndefined


@cache
def _env(package: str) -> Environment:
    return Environment(
        loader=PackageLoader(package, "prompts"),
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
    )


def render_prompt(package: str, name: str, /, **context: object) -> str:
    return _env(package).get_template(name).render(**context)


def clean_llm_line(text: str | None, *, sentinel: str, strip_chars: str = "'") -> str | None:
    text = (text or "").strip()
    if not text:
        return None
    cleaned = text.splitlines()[0].strip().strip(strip_chars).strip()
    if not cleaned or sentinel in cleaned.upper():
        return None
    return cleaned
