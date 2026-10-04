"""Run both offline modes; regression is mandatory once trusted baselines exist."""

import json
import os
import subprocess
from pathlib import Path

from lead_cleaner.evaluation.quality_cli import main
from lead_cleaner.evaluation.quality_context import git, trusted_json


def run_ci() -> int:
    root = Path(__file__).resolve().parents[1]
    candidate = git(root, "rev-parse", "HEAD")
    reference = os.environ.get("QUALITY_BASE_SHA") or git(
        root, "rev-parse", "refs/remotes/origin/main"
    )
    if git(root, "rev-parse", reference) != git(root, "rev-parse", "refs/remotes/origin/main"):
        raise ValueError("trusted reference must be current origin/main")
    exists = (
        subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "cat-file",
                "-e",
                f"{reference}:config/quality_baseline.v1.json",
            ],
            capture_output=True,
        ).returncode
        == 0
    )
    if exists:
        index = trusted_json(root, reference, "config/quality_baseline_index.v1.json")
    else:
        index = {"accepted": {}}
    exits = []
    for mode in ("rule_only", "mocked_model"):
        directory = root / "data/runtime/ci-quality" / mode
        execution = main(["run", "--mode", mode, "--out", str(directory)])
        exits.append(execution)
        if not (directory / "COMPLETED").is_file():
            exits.append(2)
            continue
        gate = "regression" if mode in index.get("accepted", {}) else "inventory"
        if gate == "inventory":
            print(f"BOOTSTRAP: {mode} has no business-accepted baseline; release remains blocked.")
        args = [
            "check",
            "--gate",
            gate,
            "--run",
            str(directory),
            "--candidate-sha",
            candidate,
            "--review-set",
            "empty",
            "--out",
            str(root / "data/runtime/ci-quality" / (mode + "-decision")),
        ]
        if gate == "regression":
            args += [
                "--trusted-ref",
                reference,
                "--baseline-index",
                str(root / "config/quality_baseline_index.v1.json"),
            ]
        exits.append(main(args))
    print(json.dumps({"exit_codes": exits, "product_release_status": "not_evaluated"}))
    return max(exits, default=2)


if __name__ == "__main__":
    raise SystemExit(run_ci())
