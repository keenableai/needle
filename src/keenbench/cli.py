import fire
from dotenv import load_dotenv

from keenbench import __version__
from keenbench.companyfill.cli import Companyfill
from keenbench.finance.cli import Finance
from keenbench.freshstream.cli import Freshstream
from keenbench.legal.cli import Legal
from keenbench.rarestream.cli import Rarestream
from keenbench.scholar.cli import Scholar


class Keenbench:
    def __init__(self) -> None:
        self.companyfill = Companyfill()
        self.finance = Finance()
        self.freshstream = Freshstream()
        self.legal = Legal()
        self.rarestream = Rarestream()
        self.scholar = Scholar()

    def version(self) -> str:
        return f"keenbench {__version__}"


def main() -> None:
    load_dotenv()
    fire.Fire(Keenbench, name="keenbench")


if __name__ == "__main__":
    main()
