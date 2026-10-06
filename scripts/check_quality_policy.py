"""Run this stdlib-only guard FROM THE TRUSTED BASE before importing candidate code."""

import argparse
import fnmatch
import json
import subprocess
from pathlib import Path


def _protected_worktree_files(root: Path, patterns: list[str]) -> set[str]:
    """Match Git's fnmatch scope, including nested and ignored worktree files."""
    matched = set()
    for pattern in patterns:
        parts = pattern.split("/")
        prefix = []
        for part in parts:
            if any(character in part for character in "*?["):
                break
            prefix.append(part)
        base = root.joinpath(*prefix)
        # Exact paths need no traversal. Wildcards may match '/' in fnmatch,
        # so enumerate recursively only beneath their fixed directory prefix.
        candidates = (base,) if len(prefix) == len(parts) else base.rglob("*")
        for path in candidates:
            if path.is_file():
                name = path.relative_to(root).as_posix()
                if fnmatch.fnmatchcase(name, pattern):
                    matched.add(name)
    return matched


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--trusted-ref", required=True)
    parser.add_argument("--bootstrap", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()

    def git(*parts):
        return subprocess.run(
            ["git", "-C", str(root), *parts], check=True, capture_output=True
        ).stdout

    ref = git("rev-parse", "--verify", args.trusted_ref + "^{commit}").decode().strip()
    if ref != git("rev-parse", "refs/remotes/origin/main").decode().strip():
        raise ValueError("trusted ref is not the current accepted target branch")
    try:
        protocol = json.loads(git("show", f"{ref}:config/quality_baseline.v1.json"))
    except subprocess.CalledProcessError:
        if args.bootstrap:
            print(
                "BOOTSTRAP ONLY: no accepted evaluation protocol exists; business release is not approved."
            )
            return 0
        raise
    if args.bootstrap:
        raise ValueError("bootstrap cannot replace an existing accepted protocol")
    patterns = list(protocol["protected_patterns"])
    names = git("ls-tree", "-r", "--name-only", ref).decode().splitlines()
    # Read only the fixed path from the accepted main tree. Candidate files and
    # command-line arguments cannot opt out of an accepted supplementary policy.
    for supplementary, protocol_id in (
        ("config/quality_answerability.v1.json", "p0-02.v1"),
        ("config/quality_answerability.v2.json", "p0-02.v2"),
    ):
        if supplementary not in names:
            continue
        extra = json.loads(git("show", f"{ref}:{supplementary}"))
        additions = extra["protected_patterns"]
        if (
            extra.get("protocol_id") != protocol_id
            or not isinstance(additions, list)
            or not additions
            or any(not isinstance(pattern, str) or not pattern for pattern in additions)
        ):
            raise ValueError("invalid accepted answerability protection patterns")
        patterns.extend(additions)
    expected = {name for name in names if any(fnmatch.fnmatchcase(name, p) for p in patterns)}
    actual = _protected_worktree_files(root, patterns)
    changed = sorted(expected ^ actual)
    for name in sorted(expected & actual):
        if git("show", f"{ref}:{name}").replace(b"\r\n", b"\n") != (
            root / name
        ).read_bytes().replace(b"\r\n", b"\n"):
            changed.append(name)
    if changed:
        print(json.dumps({"protocol_upgrade_requires_review": sorted(set(changed))}))
        return 3
    print(json.dumps({"trusted_ref": ref, "protected_files_verified": len(expected)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
