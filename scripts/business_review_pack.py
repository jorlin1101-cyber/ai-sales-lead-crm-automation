"""Assemble a local, source-bound sales review packet from two sealed replays."""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
from collections import Counter
from pathlib import Path
from time import perf_counter
from typing import Any

from lead_cleaner.answerability_evaluation.dataset import load_dataset
from lead_cleaner.answerability_evaluation.reports import content_hash, key as report_key, load_run

ROOT = Path(__file__).resolve().parents[1]
MODES = ("rule_only", "mocked_model")
DIMS = ("answer_content", "grounding", "clarification")


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def assemble(parent: Path, standard: dict[str, Any]) -> tuple[list[dict], dict]:
    data = load_dataset(ROOT, standard["protocol"])
    runs = {mode: load_run(parent / mode) for mode in MODES}
    revisions = {(r["case_id"], r["turn_id"]): r for r in standard["revisions"]}
    signatures = {(s["case_id"], s["turn_id"]): s for s in standard["confirmed_scope"]}
    observations = {}
    checks = {}
    template_keys = {}
    for mode, run in runs.items():
        meta = run["metadata"]
        if meta["mode"] != mode or any(
            meta[k] != data[k] for k in ("dataset_hash", "knowledge_hash", "protocol_id")
        ):
            raise ValueError("The replay mode or frozen corpus does not match the standard")
        for row in run["observations"]:
            observations[mode, row["case_id"], row["turn_id"]] = row
        for a in run["assertions"]:
            checks.setdefault((mode, a["case_id"], a["turn_id"]), {})[a["assertion_id"]] = a[
                "behavior_status"
            ]
            if a["assertion_id"] in DIMS:
                template_keys.setdefault((mode, a["case_id"], a["turn_id"]), {})[
                    a["assertion_id"]
                ] = list(report_key(a))
    if len({r["metadata"]["code_hash"] for r in runs.values()}) != 1:
        raise ValueError("Two modes must use the same product code")
    rows = []
    for case in data["cases"]:
        cid = case["case_id"]
        corpus = {
            c["chunk"]["chunk_id"]: c["chunk"]
            for c in data["snapshots"][case["snapshot_id"]]["chunks"]
        }
        history: dict[str, str] = {}
        for turn in case["turns"]:
            tid = turn["turn_id"]
            key = (cid, tid)
            update = revisions.get(key)
            if update and update["frozen_label"] != turn["answerability"]:
                raise ValueError(f"Stale label revision for {key}")
            for mode in MODES:
                obs = observations.pop((mode, cid, tid))
                if obs["input_message"] != turn["message"] or obs["history"] != list(
                    history.values()
                ):
                    raise ValueError(f"Customer input or source history mismatch for {key}")
                retrieved = {c["chunk_id"] for c in obs["retrieved_chunks"]}
                supplied = {c["chunk_id"] for c in obs["provided_context"]}
                reverse = {msg: source for source, msg in obs["message_id_map"].items()}
                facets = []
                for facet in turn["facets"]:
                    refs = []
                    for ref in facet["evidence_refs"]:
                        chunk = corpus[ref["chunk_id"]]
                        if chunk["text"][ref["start"] : ref["end"]] != ref["quote"]:
                            raise ValueError(f"Source span changed for {key}")
                        refs.append(
                            {
                                **ref,
                                "title": chunk["source_title"],
                                "section": chunk["section"],
                                "retrieved": ref["chunk_id"] in retrieved,
                                "supplied": ref["chunk_id"] in supplied,
                            }
                        )
                    facets.append(
                        {
                            "id": facet["facet_id"],
                            "description": facet["description"],
                            "frozen_answerable": facet["answerable"],
                            "scope": facet["rationale"],
                            "reasons": facet["reasons"],
                            "required_fields": facet["required_customer_fields"],
                            "forbidden": facet["forbidden_claims"],
                            "evidence": refs,
                        }
                    )
                item = {
                    "case_id": cid,
                    "turn_id": tid,
                    "mode": mode,
                    "group": case["evaluation_group"],
                    "customer": turn["message"],
                    "history": dict(history),
                    "time": turn["evaluation_time"],
                    "snapshot": case["snapshot_id"],
                    "frozen_label": turn["answerability"],
                    "review_label": update["review_label"] if update else turn["answerability"],
                    "revision": update,
                    "confirmation": signatures.get(key),
                    "facets": facets,
                    "reply": obs["reply_text"],
                    "facts": [
                        {**f, "source_turn": reverse.get(f["source_message_id"])}
                        for f in obs["facts"]
                    ],
                    "assertions": checks[mode, cid, tid],
                    "review_template_keys": template_keys[mode, cid, tid],
                    "standard": standard["version"],
                    "manifest": runs[mode]["manifest_hash"],
                }
                item["evidence_id"] = content_hash(item)
                rows.append(item)
            history[tid] = turn["message"]
    if observations:
        raise ValueError("Unexpected observations outside the frozen cohort")
    return rows, {
        m: {
            "manifest": r["manifest_hash"],
            "commit": r["metadata"]["tested_commit"],
            "code_hash": r["metadata"]["code_hash"],
        }
        for m, r in runs.items()
    }


def adjudicate(
    rows: list[dict], ratings: list[dict], resolutions: list[dict] | None = None
) -> tuple[list[dict], list[dict]]:
    valid = {(r["evidence_id"], dim) for r in rows for dim in DIMS}
    entries: dict[tuple, list[dict]] = {}
    reviewers = set()
    for grade in ratings:
        key = grade["evidence_id"], grade["dimension"]
        identity = (*key, grade["reviewer"])
        if (
            key not in valid
            or identity in reviewers
            or not grade["reviewer"].strip()
            or not grade["reason"].strip()
            or grade["grade"] not in ("pass", "partial", "fail")
        ):
            raise ValueError(
                "Rating has an unknown evidence ID, duplicate, or incomplete rationale"
            )
        reviewers.add(identity)
        entries.setdefault(key, []).append(grade)
    resolved = {}
    for record in resolutions or []:
        key = record["evidence_id"], record["dimension"]
        choices = entries.get(key, [])
        if (
            key in resolved
            or len({c["grade"] for c in choices}) < 2
            or record["grade"] not in ("pass", "partial", "fail")
            or not record["reason"].strip()
            or not record["reviewer"].strip()
            or sorted(record["reviewed_opinions"]) != sorted(c["reviewer"] for c in choices)
        ):
            raise ValueError(
                "Resolution must bind one existing disagreement and all original opinions"
            )
        resolved[key] = record
    decisions, queue = [], []
    for row in rows:
        for dim in DIMS:
            key = row["evidence_id"], dim
            choices = entries.get(key, [])
            values = {grade["grade"] for grade in choices}
            status = (
                "pending"
                if not choices
                else "disagreement"
                if len(values) > 1
                else choices[0]["grade"]
            )
            item = {k: row[k] for k in ("case_id", "turn_id", "mode", "group", "evidence_id")}
            if key in resolved:
                item["resolution"] = resolved[key]
                status = resolved[key]["grade"]
            item.update(dimension=dim, status=status, ratings=choices)
            decisions.append(item)
            if status != "pass":
                queue.append(item)
    return decisions, queue


def render(
    folder: Path, rows: list[dict], decisions: list[dict], queue: list[dict], provenance: dict
) -> None:
    write(folder / "evidence.json", rows)
    write(folder / "judgments.json", decisions)
    write(folder / "review-queue.json", queue)
    write(folder / "manifests.json", provenance)
    counts = Counter((d["group"], d["mode"], d["dimension"], d["status"]) for d in decisions)
    lines = [
        "# Sales inquiry business review",
        "",
        f"{len(rows)} replies · {len(decisions)} dimension judgments",
        "",
        "| Cohort | Mode | Dimension | Status | Count |",
        "|---|---|---|---|---:|",
    ]
    lines.extend(f"| {g} | {m} | {d} | {s} | {n} |" for (g, m, d, s), n in sorted(counts.items()))
    causes = Counter(
        (d["group"], reason.get("cause", "unspecified"))
        for d in queue
        for reason in d["ratings"]
        if reason["grade"] != "pass"
    )
    if causes:
        lines.extend(["", "| Cohort | Reported failure cause | Ratings |", "|---|---|---:|"])
        lines.extend(f"| {group} | {cause} | {n} |" for (group, cause), n in sorted(causes.items()))
    (folder / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_pair", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--ratings", action="append", type=Path, default=[])
    parser.add_argument("--resolutions", type=Path)
    parser.add_argument("--trials", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.trials <= 50:
        parser.error("--trials must be from 1 to 50")
    if args.output.exists():
        parser.error("choose a new output directory to preserve existing review records")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    standard = read(ROOT / "data/business_review/standard.v1.json")
    ratings = [grade for path in args.ratings for grade in read(path)]
    resolutions = read(args.resolutions) if args.resolutions else []
    times = []
    with tempfile.TemporaryDirectory(dir=args.output.parent) as staging:
        target = Path(staging) / "review"
        target.mkdir()
        for _ in range(args.trials):
            start = perf_counter()
            rows, provenance = assemble(args.run_pair, standard)
            middle = perf_counter()
            decisions, queue = adjudicate(rows, ratings, resolutions)
            render(target, rows, decisions, queue, provenance)
            times.append(
                {"assembly_seconds": middle - start, "report_seconds": perf_counter() - middle}
            )
        write(
            target / "timing.json",
            {
                "trials": times,
                "medians": {k: statistics.median(t[k] for t in times) for k in times[0]},
                "unit": "full batch",
                "manual_review_time": None,
                "scope": "local replay assembly and report IO",
            },
        )
        target.rename(args.output)


if __name__ == "__main__":
    main()
