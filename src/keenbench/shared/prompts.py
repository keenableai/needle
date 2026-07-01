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
