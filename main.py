from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
BOSS_ROOT = PROJECT_ROOT / "boss"


def main(argv: list[str] | None = None) -> int:
    if not (BOSS_ROOT / "pyproject.toml").exists():
        print("boss submodule is not initialized. Run: git submodule update --init --recursive")
        return 1

    command = ["uv", "run", "--directory", str(BOSS_ROOT), "python", "-m", "boss"]
    if argv is None:
        argv = sys.argv[1:]

    completed = subprocess.run(command + argv, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
