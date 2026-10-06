"""Run both P0-02 modes; accepted modes may never silently become inventory."""

import json
import os
import subprocess
from pathlib import Path

from lead_cleaner.answerability_evaluation.cli import main
from lead_cleaner.answerability_evaluation.trust import git, safe_relative, trusted_json
from lead_cleaner.answerability_evaluation.registry import ACTIVE_PROTOCOL, protocol_spec

PROTOCOL = protocol_spec(ACTIVE_PROTOCOL)["policy_path"]
INDEX = protocol_spec(ACTIVE_PROTOCOL)["index_path"]
TRUST = protocol_spec(ACTIVE_PROTOCOL)["trust_path"]


def run_ci() -> int:
    root = Path(__file__).resolve().parents[1]
    candidate = git(root, "rev-parse", "HEAD")
    reference = os.environ.get("ANSWERABILITY_BASE_SHA") or git(
        root, "rev-parse", "refs/remotes/origin/main"
    )
    if git(root, "rev-parse", reference) != git(root, "rev-parse", "refs/remotes/origin/main"):
        raise ValueError("trusted reference must be current origin/main")
    exists = (
        subprocess.run(
            ["git", "-C", str(root), "cat-file", "-e", f"{reference}:{PROTOCOL}"],
            capture_output=True,
        ).returncode
        == 0
    )
    accepted = {}
    if exists:
        protocol = trusted_json(root, reference, PROTOCOL)
        if protocol.get("protocol_id") != ACTIVE_PROTOCOL:
            raise ValueError("invalid accepted answerability protocol")
        index = trusted_json(root, reference, INDEX)
        if index.get("protocol_id") != ACTIVE_PROTOCOL:
            raise ValueError("invalid accepted answerability index protocol")
        accepted = index["accepted"]
        trust = trusted_json(root, reference, TRUST)
        latest = trust.get("latest_accepted_baselines")
        registered = trust.get("accepted_baselines")
        if (
            trust.get("protocol_id") != ACTIVE_PROTOCOL
            or not isinstance(accepted, dict)
            or not isinstance(latest, dict)
            or not isinstance(registered, dict)
            or set(accepted) != set(latest)
            or not set(accepted) <= {"rule_only", "mocked_model"}
            or registered
            and not latest
        ):
            raise ValueError("trusted baseline index and acceptance registry disagree")
        identities = set()
        for mode, entry in accepted.items():
            record = (
                trusted_json(root, reference, safe_relative(entry))
                if isinstance(entry, str)
                else entry
            )
            if not isinstance(record, dict):
                raise ValueError("invalid trusted baseline record")
            identity, manifest = record.get("acceptance_id"), record.get("manifest_hash")
            if (
                record.get("protocol_id") != ACTIVE_PROTOCOL
                or not isinstance(identity, str)
                or not identity
                or not isinstance(manifest, str)
                or not manifest
                or latest[mode] != identity
                or registered.get(identity) != manifest
                or identity in identities
            ):
                raise ValueError("trusted baseline record is not the registered latest acceptance")
            identities.add(identity)
    exits = []
    prefix = ["--project-root", str(root)]
    for mode in ("rule_only", "mocked_model"):
        directory = root / "data/runtime/ci-answerability" / mode
        exits.append(main([*prefix, "run", "--mode", mode, "--out", str(directory)]))
        if not (directory / "COMPLETED").is_file():
            exits.append(2)
            continue
        gate = "regression" if mode in accepted else "inventory"
        if gate == "inventory":
            print(
                f"BOOTSTRAP ONLY: {mode} has no accepted P0-02 baseline; inventory is not formal acceptance or product release."
            )
        args = [
            *prefix,
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
            str(root / "data/runtime/ci-answerability" / (mode + "-decision")),
        ]
        if gate == "regression":
            args += ["--trusted-ref", reference]
        exits.append(main(args))
    print(json.dumps({"exit_codes": exits, "product_release_status": "not_evaluated"}))
    return max(exits, default=2)


if __name__ == "__main__":
    raise SystemExit(run_ci())
