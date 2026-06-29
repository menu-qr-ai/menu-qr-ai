import subprocess
import sys


def main() -> None:
    raise SystemExit(subprocess.call([sys.executable, "-m", "alembic", "upgrade", "head"]))


if __name__ == "__main__":
    main()
