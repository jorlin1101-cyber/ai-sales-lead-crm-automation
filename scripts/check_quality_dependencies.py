"""Verify container constraints are an exact uv.lock export, without changing either."""

import subprocess
from pathlib import Path


def normalized_requirements(text: str) -> list[str]:
    return sorted(
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def check_requirements(root: Path) -> bool:
    export = subprocess.run(
        [
            "uv",
            "export",
            "--locked",
            "--extra",
            "dev",
            "--no-emit-project",
            "--no-hashes",
            "--no-header",
            "--no-annotate",
            "--offline",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return normalized_requirements(export) == normalized_requirements(
        (root / "requirements.txt").read_text(encoding="utf-8")
    )


if __name__ == "__main__":
    valid = check_requirements(Path(__file__).resolve().parents[1])
    print(
        "Container constraints match uv.lock."
        if valid
        else "Container constraints differ from uv.lock."
    )
    raise SystemExit(0 if valid else 1)
