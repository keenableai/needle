import fire
from dotenv import load_dotenv

from keenbench import __version__
from keenbench.companyfill.cli import Companyfill
from keenbench.freshstream.cli import Freshstream
from keenbench.rarestream.cli import Rarestream


class Keenbench:
    def __init__(self) -> None:
        self.companyfill = Companyfill()
        self.freshstream = Freshstream()
        self.rarestream = Rarestream()

    def version(self) -> str:
        return f"keenbench {__version__}"


def main() -> None:
    load_dotenv()
    fire.Fire(Keenbench, name="keenbench")


if __name__ == "__main__":
    main()
