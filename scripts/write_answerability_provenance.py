"""Write the P0-02 outer artifact index after upload, outside sealed reports."""

import argparse
import json
import os
from pathlib import Path

from lead_cleaner.answerability_evaluation.reports import load_run


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    required = (
        "GITHUB_REPOSITORY",
        "GITHUB_WORKFLOW_SHA",
        "GITHUB_RUN_ID",
        "GITHUB_RUN_ATTEMPT",
        "ANSWERABILITY_ARTIFACT_ID",
        "ANSWERABILITY_ARTIFACT_DIGEST",
    )
    if any(not os.environ.get(name, "").strip() for name in required):
        raise ValueError("artifact provenance requires nonempty upload and workflow outputs")
    records = []
    for marker in sorted(args.root.glob("*/COMPLETED")):
        if args.out.resolve().is_relative_to(marker.parent.resolve()):
            raise ValueError("provenance index must remain outside sealed reports")
        run = load_run(marker.parent)
        records.append(
            {
                "directory": str(marker.parent),
                "artifact_prefix": marker.parent.name,
                "provenance": {
                    "repository": os.environ["GITHUB_REPOSITORY"],
                    "tested_commit": run["metadata"]["tested_commit"],
                    "workflow_sha": os.environ["GITHUB_WORKFLOW_SHA"],
                    "run_id": os.environ["GITHUB_RUN_ID"],
                    "attempt": os.environ["GITHUB_RUN_ATTEMPT"],
                    "artifact_id": os.environ["ANSWERABILITY_ARTIFACT_ID"],
                    "artifact_digest": os.environ["ANSWERABILITY_ARTIFACT_DIGEST"],
                    "manifest_hash": run["manifest_hash"],
                },
            }
        )
    if not records:
        raise ValueError("no completed answerability reports to bind to the artifact")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(
            {"schema_version": "answerability-provenance.v1", "reports": records},
            stream,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )


if __name__ == "__main__":
    main()
