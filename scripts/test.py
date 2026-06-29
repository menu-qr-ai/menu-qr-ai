import subprocess
import sys


def main() -> None:
    commands = [
        [sys.executable, "-m", "compileall", "app", "tests"],
        [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
        [sys.executable, "-m", "pytest"],
        [sys.executable, "-m", "ruff", "check", "."],
    ]
    for command in commands:
        result = subprocess.call(command)
        if result != 0:
            raise SystemExit(result)


if __name__ == "__main__":
    main()
