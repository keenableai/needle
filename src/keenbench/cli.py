import fire
from dotenv import load_dotenv

from keenbench import __version__
from keenbench.freshstream.cli import Freshstream


class Keenbench:
    def __init__(self) -> None:
        self.freshstream = Freshstream()

    def version(self) -> str:
        return f"keenbench {__version__}"


def main() -> None:
    load_dotenv()
    fire.Fire(Keenbench, name="keenbench")


if __name__ == "__main__":
    main()
