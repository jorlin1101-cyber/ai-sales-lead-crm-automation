"""Replay the frozen single-business-day batch with an explicitly bound product clock."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from lead_cleaner.answerability_evaluation.cli import main as run_protocol
from lead_cleaner.answerability_evaluation.dataset import load_dataset
from lead_cleaner.answerability_evaluation.reports import file_hash, write_record
from lead_cleaner.services.conversation_service import ConversationService


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["rule_only", "mocked_model"], required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root = Path.cwd()
    data = load_dataset(root, "p0-02.v2")
    dates = {
        datetime.fromisoformat(t["evaluation_time"]).date()
        for case in data["cases"]
        for t in case["turns"]
    }
    if len(dates) != 1:
        parser.error("This cohort runner requires one shared evaluation date")
    day = dates.pop()
    receipt = args.out.parent / (args.out.name + ".business-clock.json")
    if receipt.exists() or args.out.exists():
        parser.error("Choose a fresh output path")
    original_init = ConversationService.__init__

    def initialize(service, store):
        original_init(service, store, business_date=lambda: day)

    with patch.object(ConversationService, "__init__", initialize):
        result = run_protocol(
            ["--project-root", str(root), "run", "--mode", args.mode, "--out", str(args.out)]
        )
    if result == 0:
        write_record(
            receipt,
            {
                "business_date": day.isoformat(),
                "clock_source": "evaluation_time",
                "mode": args.mode,
                "manifest": file_hash(args.out / "manifest.json"),
            },
        )
    return result


if __name__ == "__main__":
    raise SystemExit(main())
