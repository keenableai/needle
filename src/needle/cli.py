import fire
from dotenv import load_dotenv

from needle import APP_NAME, __version__
from needle.agentic_rare.cli import AgenticRare
from needle.finance.cli import Finance
from needle.legal.cli import Legal
from needle.news.cli import News
from needle.scholar.cli import Scholar


class Needle:
    def __init__(self) -> None:
        self.finance = Finance()
        self.news = News()
        self.legal = Legal()
        self.agentic_rare = AgenticRare()
        self.scholar = Scholar()

    def version(self) -> str:
        return f"{APP_NAME} {__version__}"


def main() -> None:
    load_dotenv()
    fire.Fire(Needle, name=APP_NAME)


if __name__ == "__main__":
    main()
