#!/usr/bin/env python3
"""What an end-to-end run must have left on its pull request, read back with
the engine's own readers.

Always: the summary comment is the pull request's last item (no review or
comment after it) and names this run.

When the pull request carries the fixture (a GOOSE-REVIEW-E2E line under
tests/e2e/fixture/): one open thread on it, not one per lane -- the slow
lane replied in the first lane's thread -- signed by both reviewing
models, and the backup verifier confirmed the lane whose verifier answered
empty.

Usage: GH_TOKEN=... assert.py --repo o/r --pr N --run-id ID --fixture PATH
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import goose_review as g  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", required=True, type=int)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--fixture", required=True, help="the fixture file, if this pull request adds it")
    parser.add_argument("--models", nargs="+", default=["fake-a", "fake-b"], help="the reviewing models")
    parser.add_argument("--backup", default="fake-backup")
    args = parser.parse_args()
    token = os.environ["GH_TOKEN"]
    failures = []

    comments = g.paged(f"/repos/{args.repo}/issues/{args.pr}/comments", token)
    reviews = g.paged(f"/repos/{args.repo}/pulls/{args.pr}/reviews", token)
    last = max(comments, key=lambda c: c["id"], default=None)
    if not last or g.SUMMARY_MARKER not in (last.get("body") or ""):
        failures.append("the last comment is not the summary")
    else:
        later = [r for r in reviews if (r.get("submitted_at") or "") > last["created_at"]]
        if later:
            failures.append(f"{len(later)} review(s) came after the summary")
        if args.run_id not in last["body"]:
            failures.append("the summary does not name this run")

    if Path(args.fixture).exists():
        _, threads = g.goose_threads(args.repo, args.pr, token)
        mine = [t for t in threads if t["path"] == args.fixture and not t["isResolved"]]
        if len(mine) != 1:
            failures.append(f"{len(mine)} open threads on {args.fixture}, expected one")
        else:
            bodies = [c.get("body") or "" for c in mine[0]["all"]]
            for model in args.models:
                if not any(f"**{model}**" in b for b in bodies):
                    failures.append(f"no comment by {model} in the thread")
            if not any(args.backup in b for b in bodies):
                failures.append(f"no finding verified by {args.backup} in the thread")
        if last and args.backup not in (last.get("body") or ""):
            failures.append(f"the summary does not show {args.backup}")

    for failure in failures:
        print(f"::error::{failure}")
    if failures:
        raise SystemExit(1)
    print("end-to-end: the pull request is as expected")


if __name__ == "__main__":
    main()
