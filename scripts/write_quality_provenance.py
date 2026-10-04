"""Create an outer artifact index AFTER upload; never rewrite sealed reports."""

import argparse
import json
import os
from pathlib import Path

from lead_cleaner.evaluation.quality_report import load_run


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
        "QUALITY_ARTIFACT_ID",
        "QUALITY_ARTIFACT_DIGEST",
    )
    if any(not os.environ.get(name, "").strip() for name in required):
        raise ValueError("artifact provenance requires nonempty upload and workflow outputs")
    records = []
    for marker in sorted(args.root.glob("*/COMPLETED")):
        run = load_run(marker.parent)
        metadata = run["metadata"]
        records.append(
            {
                "directory": str(marker.parent),
                "artifact_prefix": marker.parent.name,
                "provenance": {
                    "repository": os.environ["GITHUB_REPOSITORY"],
                    "tested_commit": metadata["tested_commit"],
                    "workflow_sha": os.environ["GITHUB_WORKFLOW_SHA"],
                    "run_id": os.environ["GITHUB_RUN_ID"],
                    "attempt": os.environ["GITHUB_RUN_ATTEMPT"],
                    "artifact_id": os.environ["QUALITY_ARTIFACT_ID"],
                    "artifact_digest": os.environ["QUALITY_ARTIFACT_DIGEST"],
                    "manifest_hash": run["manifest_hash"],
                },
            }
        )
    if not records:
        raise ValueError("no completed quality reports to bind to the artifact")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(
            {"schema_version": "p0-quality-provenance.v1", "reports": records},
            stream,
            ensure_ascii=False,
            indent=2,
        )


if __name__ == "__main__":
    main()
