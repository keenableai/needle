import fire
from dotenv import load_dotenv

from keenbench import __version__
from keenbench.agentic_rare.cli import AgenticRare
from keenbench.finance.cli import Finance
from keenbench.findallmcp.cli import FindallMcp
from keenbench.legal.cli import Legal
from keenbench.news.cli import News
from keenbench.scholar.cli import Scholar


class Keenbench:
    def __init__(self) -> None:
        self.finance = Finance()
        self.findallmcp = FindallMcp()
        self.news = News()
        self.legal = Legal()
        self.agentic_rare = AgenticRare()
        self.scholar = Scholar()

    def version(self) -> str:
        return f"keenbench {__version__}"


def main() -> None:
    load_dotenv()
    fire.Fire(Keenbench, name="keenbench")


if __name__ == "__main__":
    main()
