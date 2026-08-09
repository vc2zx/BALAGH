from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def run() -> None:
    project_root = Path(__file__).resolve().parents[2]
    app_path = project_root / "app.py"
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", str(app_path)],
        check=True,
    )


if __name__ == "__main__":
    run()
