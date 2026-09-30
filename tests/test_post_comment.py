"""The post_comment tool: the denials given before any model looks at a
finding, the MCP server Goose talks to, and the poster that posts each
confirmed finding from a process of its own.
Run: python3 -m unittest discover -s tests"""

import argparse
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import goose_review as g  # noqa: E402

CHUNK = """diff --git a/a.txt b/a.txt
--- a/a.txt
+++ b/a.txt
@@ -7,7 +7,7 @@
 7
 8
 9
-10
+ten
 11
 12
 13
@@ -40,2 +40,3 @@
 40
+40a
 41
"""


def finding(path="a.txt", start=10, end=None, summary="wrong"):
    return {"severity": "high", "path": path, "line_start": start, "line_end": end or start,
            "summary": summary, "check": "c"}


class PrecheckTest(unittest.TestCase):
    def test_hunk_ranges(self):
        self.assertEqual(g.hunk_ranges(CHUNK), [(7, 13), (40, 42)])

    def test_a_finding_on_a_changed_hunk_passes(self):
        self.assertIsNone(g.precheck(finding(start=10), {"a.txt": CHUNK}, []))
        self.assertIsNone(g.precheck(finding(start=41), {"a.txt": CHUNK}, []))

    def test_a_file_the_change_does_not_touch_is_denied(self):
        self.assertEqual(g.precheck(finding("b.txt"), {"a.txt": CHUNK}, [])[0], "outside")

    def test_lines_outside_the_hunks_are_denied_with_the_hunks_named(self):
        kind, why = g.precheck(finding(start=25), {"a.txt": CHUNK}, [])
        self.assertEqual(kind, "outside")
        self.assertIn("outside the changed hunks (7-13, 40-42)", why)

    def test_the_lines_of_a_posted_comment_are_denied(self):
        kind, why = g.precheck(finding(start=11), {"a.txt": CHUNK}, [finding(start=9, summary="already said")])
        self.assertEqual(kind, "duplicate")
        self.assertIn("already posted at a.txt:9-9", why)
        self.assertIn("already said", why)

    def test_a_posted_comment_elsewhere_does_not_deny(self):
        self.assertIsNone(g.precheck(finding(start=41), {"a.txt": CHUNK}, [finding(start=10)]))


class ServerTest(unittest.TestCase):
    """The server over stdio, as Goose 1.52 speaks to it: `server/discover`
    first (refused), then `initialize`. Only denials that need no model."""

    def test_handshake_and_denials(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp, "repo")
            repo.mkdir()
            run = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)  # noqa: E731
            run("init", "-q")
            (repo / "a.txt").write_text("".join(f"{n}\n" for n in range(1, 31)))
            run("add", ".")
            run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base")
            (repo / "a.txt").write_text("".join(("ten" if n == 10 else str(n)) + "\n" for n in range(1, 31)))
            run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "head")
            spec = Path(tmp, "spec.json")
            spec.write_text(json.dumps({
                "base": "HEAD~1", "verifiers": [["p", "m"]], "context": None, "answered": None,
                "config": {"checks_dir": ".agents/checks", "check": None, "facts_dir": ".agents/facts", "ignore": None,
                           "tools_file": None, "tools": None, "rules_file": None},
                # Too little time left to verify: the call that passes the prechecks is withheld, no model runs.
                "deadline": time.time() + 30, "check": "c", "label": "c#0",
                "posted": str(Path(tmp, "posted.jsonl")), "calls": str(Path(tmp, "calls.jsonl")),
                "pending": str(Path(tmp, "pending.jsonl")), "poster": None,
            }))

            def call(n, **arguments):
                return {"jsonrpc": "2.0", "id": n, "method": "tools/call",
                        "params": {"name": "post_comment", "arguments": {"severity": "high", "summary": "x", **arguments}}}

            requests = [
                {"jsonrpc": "2.0", "id": 0, "method": "server/discover"},
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                call(3, path="b.txt", line_start=3),
                call(4, path="a.txt", line_start=25),
                call(5, path="a.txt", line_start=10),
            ]
            server = subprocess.Popen([sys.executable, str(ROOT / "goose_review.py"), "mcp", "--spec", str(spec)],
                                      cwd=repo, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            server.stdin.write("".join(json.dumps(r) + "\n" for r in requests))
            server.stdin.flush()
            answers = {}
            while len(answers) < 6:
                message = json.loads(server.stdout.readline())
                answers[message["id"]] = message
            server.stdin.close()
            server.wait(timeout=10)

            self.assertEqual(answers[0]["error"]["code"], -32601)
            self.assertEqual(answers[1]["result"]["protocolVersion"], "2025-11-25")
            self.assertEqual([t["name"] for t in answers[2]["result"]["tools"]], ["post_comment"])
            text = {n: answers[n]["result"]["content"][0]["text"] for n in (3, 4, 5)}
            self.assertIn("not a file this pull request changes", text[3])
            self.assertIn("outside the changed hunks", text[4])
            self.assertIn("time is nearly up", text[5])
            outcomes = [c["outcome"] for c in map(json.loads, Path(tmp, "calls.jsonl").read_text().splitlines())]
            self.assertEqual(sorted(outcomes), ["no-time", "outside", "outside"])
            self.assertFalse(Path(tmp, "posted.jsonl").exists())


CONFIRMED = {
    "severity": "high", "path": "a.txt", "line_start": 10, "line_end": 10, "check": "c",
    "summary": "Line ten is wrong.", "trigger": "any request", "evidence": {"path": "a.txt", "line": 10},
    "verified_by": "verifier",
}
LANE = g.Lane("o/r", 7, "alpha", "h" * 40, "b" * 40, "reviewer", "verifier")
LINES = {"a.txt": g.commentable_lines(CHUNK.split("+++ b/a.txt\n", 1)[1])}


class FakeGitHub:
    """Records every write; answers the reads the poster makes."""

    def __init__(self, threads=()):
        self.posts, self.threads = [], list(threads)

    def github(self, method, url, token, body=None, accept=None):
        self.posts.append((method, url, body))
        return 201, {"html_url": f"https://github.test/{len(self.posts)}", "id": len(self.posts)}


class LiveFindingTest(unittest.TestCase):
    def test_a_confirmed_finding_passes(self):
        f, why = g.live_finding(CONFIRMED, {"verifier"})
        self.assertEqual(why, "")
        self.assertEqual((f["path"], f["line_end"], f["verified_by"]), ("a.txt", 10, "verifier"))

    def test_what_the_poster_refuses(self):
        cases = {
            "no trigger": {k: v for k, v in CONFIRMED.items() if k != "trigger"},
            "no evidence": {**CONFIRMED, "evidence": "a.txt:10"},
            "a made-up verifier": {**CONFIRMED, "verified_by": "someone"},
            "a bad severity": {**CONFIRMED, "severity": "urgent"},
            "no check": {**CONFIRMED, "check": ""},
            "a long summary": {**CONFIRMED, "summary": "x" * 4001},
            "not a mapping": ["a.txt"],
        }
        for name, raw in cases.items():
            with self.subTest(name):
                f, why = g.live_finding(raw, {"verifier"})
                self.assertIsNone(f)
                self.assertTrue(why)

    def test_a_lowered_severity_keeps_its_reason_and_a_raised_one_is_dropped(self):
        f, _ = g.live_finding({**CONFIRMED, "severity": "medium", "raised_as": "high", "severity_reason": "rare"}, {"verifier"})
        self.assertEqual((f["raised_as"], f["severity_reason"]), ("high", "rare"))
        f, _ = g.live_finding({**CONFIRMED, "raised_as": "low"}, {"verifier"})
        self.assertNotIn("raised_as", f)

    def test_secrets_are_scrubbed_from_every_text(self):
        with mock.patch.dict(os.environ, {"GOOSE_REVIEW_PROVIDER_ENV": "KEY=sk-0123456789abcdef"}):
            f = g.scrubbed({**CONFIRMED, "summary": "leak sk-0123456789abcdef", "trigger": "fedcba9876543210-ks"})
        self.assertNotIn("sk-0123456789abcdef", json.dumps(f))
        self.assertNotIn("fedcba9876543210-ks", json.dumps(f))


class PostOneTest(unittest.TestCase):
    def test_a_review_of_its_own_carrying_the_lane_marker(self):
        fake = FakeGitHub()
        with mock.patch.object(g, "github", fake.github), mock.patch.object(g, "open_threads", lambda *a: []):
            ok, url = g.post_one(CONFIRMED, LANE, LINES, "t")
        self.assertTrue(ok)
        method, path, body = fake.posts[0]
        self.assertEqual((method, path), ("POST", "/repos/o/r/pulls/7/reviews"))
        self.assertEqual(body["event"], "COMMENT")
        self.assertEqual(len(body["comments"]), 1)
        self.assertTrue(g.is_lane_review({"author": {"__typename": "Bot"}, "body": body["body"]}))
        self.assertEqual(g.posted_finding(body["comments"][0]["body"])["summary"], "Line ten is wrong.")

    def test_a_reply_in_the_open_thread_on_its_lines(self):
        fake = FakeGitHub()
        thread = {"path": "a.txt", "line": 11, "startLine": 9, "all": [{"databaseId": 99}]}
        with mock.patch.object(g, "github", fake.github), mock.patch.object(g, "open_threads", lambda *a: [thread]):
            ok, _ = g.post_one(CONFIRMED, LANE, LINES, "t")
        self.assertTrue(ok)
        self.assertEqual(fake.posts[0][1], "/repos/o/r/pulls/7/comments/99/replies")

    def test_a_line_github_takes_no_comment_on(self):
        fake = FakeGitHub()
        with mock.patch.object(g, "github", fake.github), mock.patch.object(g, "open_threads", lambda *a: []):
            ok, why = g.post_one({**CONFIRMED, "line_start": 30, "line_end": 30}, LANE, LINES, "t")
        self.assertFalse(ok)
        self.assertIn("not a line of this pull request's diff", why)
        self.assertEqual(fake.posts, [])


class PosterTest(unittest.TestCase):
    """`poster` over its socket, GitHub stubbed: the secrets come on stdin."""

    def test_round_trip_and_the_cap(self):
        fake = FakeGitHub()
        with tempfile.TemporaryDirectory() as tmp:
            sock = str(Path(tmp, "poster.sock"))
            args = argparse.Namespace(socket=sock, repo="o/r", pr=7, head_sha=LANE.head_sha, base_sha=LANE.base_sha,
                                      lane="alpha", model="reviewer", verifier=["verifier", "backup"],
                                      log=str(Path(tmp, "log.jsonl")), idle_minutes=0.02)
            stdin = io.StringIO(json.dumps({"token": "t", "routes": "", "env": "KEY=sk-0123456789abcdef", "secrets": ""}) + "\n")
            patches = [mock.patch.object(g, "github", fake.github), mock.patch.object(g, "open_threads", lambda *a: []),
                       mock.patch.object(g, "diff_lines", lambda *a: LINES), mock.patch.object(g, "MAX_LIVE_COMMENTS", 2),
                       mock.patch("sys.stdin", stdin), mock.patch.dict(os.environ, {})]
            for patch in patches:
                patch.start()
            self.addCleanup(lambda: [patch.stop() for patch in reversed(patches)])
            server = threading.Thread(target=g.cmd_poster, args=(args,), daemon=True)
            server.start()
            for _ in range(100):
                if Path(sock).exists():
                    break
                time.sleep(0.02)
            answers = [
                g.send_to_poster(sock, {**CONFIRMED, "summary": "leak sk-0123456789abcdef"}),
                g.send_to_poster(sock, {**CONFIRMED, "line_start": 41, "line_end": 41}),
                g.send_to_poster(sock, {**CONFIRMED, "line_start": 12, "line_end": 12}),
                g.send_to_poster(sock, {**CONFIRMED, "verified_by": "reviewer"}),
            ]
            server.join(timeout=5)
            self.assertEqual([a["ok"] for a in answers], [True, True, False, False])
            self.assertIn("posted its 2 comments", answers[2]["reason"])
            self.assertIn("not one of this lane's verifiers", answers[3]["reason"])
            self.assertEqual(len(fake.posts), 2)
            self.assertNotIn("sk-0123456789abcdef", json.dumps(fake.posts))
            self.assertEqual(len(Path(tmp, "log.jsonl").read_text().splitlines()), 3)


class PostTest(unittest.TestCase):
    """`post` finishing a lane: what was posted live is counted from GitHub,
    what the poster never got is posted as one review."""

    def run_post(self, tmp, pending, comments, status):
        Path(tmp, "pending.jsonl").write_text("".join(json.dumps(f) + "\n" for f in pending))
        Path(tmp, "status.json").write_text(json.dumps(status))
        fake = FakeGitHub()
        args = argparse.Namespace(repo="o/r", pr=7, head_sha=LANE.head_sha, base_sha=LANE.base_sha, lane="alpha",
                                  model="reviewer", verify_model="verifier", input=str(Path(tmp, "pending.jsonl")),
                                  status=str(Path(tmp, "status.json")), dry_run=False, result=str(Path(tmp, "r.json")))
        with mock.patch.object(g, "github", fake.github), mock.patch.object(g, "paged", lambda *a: comments), \
                mock.patch.object(g, "open_threads", lambda *a: []), mock.patch.object(g, "diff_lines", lambda *a: LINES), \
                mock.patch.object(g, "collapse_resolved", lambda *a, **k: 0), mock.patch.dict(os.environ, {"GH_TOKEN": "t"}):
            g.cmd_post(args)
        return fake, json.loads(Path(tmp, "r.json").read_text())

    def test_live_findings_are_counted_and_pending_ones_posted(self):
        live = {"user": {"type": "Bot"}, "html_url": "https://github.test/live",
                "body": g.comment_body({**CONFIRMED, "severity": "critical"}, LANE.meta)}
        other_commit = {"user": {"type": "Bot"}, "body": g.comment_body(CONFIRMED, {**LANE.meta, "commit": "x" * 40})}
        status = {"checks_run": ["c"], "checks_failed": [], "checks_skipped": [], "found": 3, "rejected": 1,
                  "duplicates": 1, "verified_by": ["verifier"]}
        with tempfile.TemporaryDirectory() as tmp:
            fake, result = self.run_post(tmp, [{**CONFIRMED, "line_start": 41, "line_end": 41}], [live, other_commit], status)
        self.assertEqual([p[1] for p in fake.posts], ["/repos/o/r/pulls/7/reviews"])
        self.assertEqual(result["counts"], {"low": 0, "medium": 0, "high": 1, "critical": 1})
        self.assertEqual(result["review_url"], "https://github.test/live")
        self.assertEqual((result["found"], result["rejected"], result["duplicates"]), (3, 1, 1))
        self.assertEqual(result["headline"], "1 critical, 1 high, each confirmed by a second model")

    def test_a_failed_review_job_still_counts_what_it_posted(self):
        live = {"user": {"type": "Bot"}, "html_url": "u", "body": g.comment_body(CONFIRMED, LANE.meta)}
        with tempfile.TemporaryDirectory() as tmp:
            fake, result = self.run_post(tmp, [], [live], {})
        self.assertEqual(fake.posts, [])
        self.assertFalse(result["did_not_run"])
        self.assertIn("did not finish", result["headline"])
        self.assertIn("1 high posted before it did", result["headline"])


if __name__ == "__main__":
    unittest.main()
