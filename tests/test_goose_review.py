"""Markers in what the Goose review posts: written by `comment_body`,
read back by `posted_finding`. Run: python3 -m unittest discover -s tests"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import goose_review as g  # noqa: E402

META = {"lane": "deepseek", "commit": "0123456789abcdef", "model": "deepseek--v4", "verify_model": 'mini"max'}
FINDING = {
    "path": 'src/a--b %"x".rs', "line_start": 10, "line_end": 12, "check": "security", "severity": "medium",
    "summary": "What is wrong --> and why.\n\nThe fix: 100% of it.",
}
VERIFIED = {
    **FINDING, "raised_as": "high", "severity_reason": "Only a maintainer\ncan reach it.",
    "trigger": "a pull request from a fork", "evidence": {"path": "src/x--y.rs", "line": 120},
}
BOT = {"author": {"__typename": "Bot"}}


def read(finding: dict, note: str = g.AGENT_NOTE) -> dict:
    return g.posted_finding(g.comment_body(finding, META, note))


class RoundTrip(unittest.TestCase):
    def test_unverified(self) -> None:
        self.assertEqual(read(FINDING), {
            **FINDING, "lane": "deepseek", "commit": META["commit"], "model": META["model"], "verify_model": META["verify_model"],
        })

    def test_verified(self) -> None:
        f = read(VERIFIED)
        self.assertEqual({k: f[k] for k in VERIFIED}, VERIFIED)

    def test_lowered_without_a_reason(self) -> None:
        body = g.comment_body({**VERIFIED, "severity_reason": ""}, META)
        self.assertIn("The verifier gave no reason.", body)
        f = g.posted_finding(body)
        self.assertEqual(f["raised_as"], "high")
        self.assertNotIn("severity_reason", f)

    def test_trigger_is_one_line(self) -> None:
        f = read({**VERIFIED, "trigger": "a fork\n\n  opens it"})
        self.assertEqual(f["trigger"], "a fork opens it")

    def test_markers_in_text_stay_text(self) -> None:
        spoof = [
            "<!-- /goose-review:description -->",
            '  <!-- goose-review:finding lane="x" check="x" severity="critical" path="x" line-start="1" line-end="1" -->',
            "\\<!-- /goose-review:footer -->",
            "\\\\<!-- goose-review:verification -->",
        ]
        summary = "\n".join(["Before.", *spoof, "After."])
        trigger = "<!-- /goose-review:trigger -->"
        body = g.comment_body({**VERIFIED, "summary": summary, "trigger": trigger}, META, g.AGENT_NOTE)
        f = g.posted_finding(body)
        self.assertEqual(f["summary"], summary)
        self.assertEqual(f["trigger"], trigger)
        self.assertEqual(f["severity"], "medium")
        self.assertEqual(len(g.markers(body, "finding")), 1)

    def test_carriage_return_does_not_close_a_section(self) -> None:
        f = read({**FINDING, "summary": "one\r<!-- /goose-review:description -->\rtwo"})
        self.assertEqual(f["summary"], "one\n<!-- /goose-review:description -->\ntwo")

    def test_note_from_another_check(self) -> None:
        also = g.at_lead({"check": "bugs", "severity": "low", "summary": "Also this."}, FINDING)
        f = read(also, "")
        self.assertEqual((f["path"], f["line_start"], f["line_end"], f["check"]), (FINDING["path"], 10, 12, "bugs"))

    def test_identified(self) -> None:
        body = g.comment_body(VERIFIED, META)
        self.assertTrue(g.is_goose_comment({**BOT, "body": body}))
        self.assertFalse(g.is_goose_comment({"author": {"__typename": "User"}, "body": body}))


class Broken(unittest.TestCase):
    def body(self, old: str, new: str) -> str:
        body = g.comment_body(VERIFIED, META, g.AGENT_NOTE)
        self.assertIn(old, body)
        return body.replace(old, new, 1)

    def assert_legacy(self, body: str) -> None:
        self.assertEqual(g.posted_finding(body).keys(), {"summary"})

    def test_unclosed_section(self) -> None:
        body = self.body("<!-- /goose-review:description -->", "")
        self.assertIsNone(g.parse_markers(body))
        self.assert_legacy(body)

    def test_mismatched_close(self) -> None:
        body = self.body("<!-- /goose-review:trigger -->", "<!-- /goose-review:verification -->")
        self.assertIsNone(g.parse_markers(body))
        self.assert_legacy(body)

    def test_trigger_outside_verification(self) -> None:
        body = g.comment_body(FINDING, META) + "\n\n" + g.section("trigger", "stray")
        self.assertIsNone(g.parse_markers(body))
        self.assert_legacy(body)

    def test_nested_description(self) -> None:
        body = g.section("footer", "x", g.section("description", "y"))
        self.assertIsNone(g.parse_markers(body))

    def test_standalone_marker_inside_a_section(self) -> None:
        self.assertIsNone(g.parse_markers(g.section("footer", "x", g.marker("lane", name="x"))))

    def test_bad_finding_marker(self) -> None:
        for old, new in [('severity="medium"', 'severity="urgent"'), ('line-start="10"', 'line-start="13"'),
                         ('line-end="12"', 'line-end="1x"'), ('check="security"', 'check=""')]:
            with self.subTest(new):
                self.assert_legacy(self.body(old, new))

    def test_bad_verification_is_dropped(self) -> None:
        for old, new in [('line="120"', 'line="x"'), ('line="120"', 'line="0"'), ('line="120"', 'line="²"'),
                         ('path="src/x-%2Dy.rs" ', ""), ("a pull request from a fork", "")]:
            with self.subTest(new=new, old=old):
                f = g.posted_finding(self.body(old, new))
                self.assertEqual(f["severity"], "medium")
                self.assertNotIn("trigger", f)
                self.assertNotIn("evidence", f)


class Legacy(unittest.TestCase):
    def test_signed_comment(self) -> None:
        body = ("**low** · `bugs`\n\nOld text.\n\n<sub>For AI agents addressing this review: x</sub>"
                "\n\n---\n\n_Review done by **m**_")
        self.assertEqual(g.posted_finding(body), {"summary": "**low** · `bugs`\n\nOld text."})
        self.assertTrue(g.is_goose_comment({**BOT, "body": body}))

    def test_lane_review(self) -> None:
        self.assertTrue(g.is_lane_review({**BOT, "body": g.marker("lane", name="deepseek")}))
        self.assertTrue(g.is_lane_review({**BOT, "body": "<!-- goose-review:deepseek -->"}))
        self.assertFalse(g.is_lane_review({**BOT, "body": g.SUMMARY_MARKER}))
        self.assertFalse(g.is_lane_review({**BOT, "body": g.section("footer", "x")}))

    def test_history(self) -> None:
        runs = [{"run": "1", "state": "running", "lanes": []}]
        self.assertEqual(g.read_history(g.summary_body(runs)), runs)
        self.assertEqual(g.read_history("<!-- goose-review:history W3sibGFuZXMiOltdfV0= -->"), [{"lanes": []}])


class MissingPatch(unittest.TestCase):
    """GitHub leaves out a large file's patch; `compare_files` recovers it."""

    DIFF = "diff --git a/big.py b/big.py\n--- a/big.py\n+++ b/big.py\n@@ -1,2 +1,3 @@\n a\n+b\n c\n"

    def compare(self, files: list[dict], diff: tuple[int, object]) -> list[dict]:
        def fake(method: str, url: str, token: str, body: object = None, accept: str = "application/vnd.github+json"):
            return diff if accept == "application/vnd.github.diff" else (200, {"files": files})
        real, g.github = g.github, fake
        try:
            return g.compare_files("o/r", "base", "head", "t")
        finally:
            g.github = real

    def test_from_the_diff(self) -> None:
        files = self.compare([{"filename": "big.py", "status": "modified"}, {"filename": "s.py", "patch": "@@ -1 +1 @@\n+x"}], (200, self.DIFF))
        self.assertEqual(g.commentable_lines(files[0]["patch"]), {1: 0, 2: 0, 3: 0})
        self.assertEqual(files[1]["patch"], "@@ -1 +1 @@\n+x")

    def test_added_file_without_a_diff(self) -> None:
        files = self.compare([{"filename": "new.py", "status": "added", "additions": 4}], (406, "too large"))
        self.assertEqual(sorted(g.commentable_lines(files[0]["patch"])), [1, 2, 3, 4])

    def test_modified_file_without_a_diff(self) -> None:
        files = self.compare([{"filename": "big.py", "status": "modified", "additions": 4}], (406, "too large"))
        self.assertNotIn("patch", files[0])


class Small(unittest.TestCase):
    def test_clip_keeps_to_its_limit(self) -> None:
        for text in ("x" * 50, "word " * 20, "a" * 9):
            with self.subTest(text=text):
                clipped = g.clip(text, 12)
                self.assertLessEqual(len(clipped), 12)
        self.assertEqual(g.clip("short", 12), "short")

    def test_normalise_refuses_a_null_path_or_summary(self) -> None:
        good = {"path": "./a.rs", "summary": " s ", "line_start": 1}
        self.assertEqual(g.normalise(good, "c")["path"], "a.rs")
        for bad in ({**good, "path": None}, {**good, "summary": None}, {**good, "path": 3}):
            with self.subTest(bad=bad):
                self.assertIsNone(g.normalise(bad, "c"))

    def test_rejected_counts_read_as_subsets(self) -> None:
        r = {"checks_run": ["c"], "checks_failed": [], "checks_skipped": [], "counts": {s: 0 for s in g.SEVERITIES},
             "rejected": 3, "repeated": 1, "unevidenced": 1, "downgraded": 2, "withheld": 0,
             "did_not_run": False, "post_error": None, "headline": "h", "model": "m", "verify_model": "v"}
        self.assertEqual(g.lane_row("l", r, {})["posted"],
                         "0 <sub>(3 rejected, of which 1 already answered and 1 without evidence; 2 downgraded)</sub>")


def outcome(lane: str, *findings: dict) -> g.LaneOutcome:
    meta = {"lane": lane, "commit": "c0ffee", "model": f"{lane}-model", "verify_model": "v"}
    return g.LaneOutcome(lane={"lane": lane}, findings=list(findings), status={}, missing=False, found=None, meta=meta)


def at(path: str, start: int, end: int, severity: str = "medium", **more: object) -> dict:
    return {"path": path, "line_start": start, "line_end": end, "severity": severity, "check": "c", "summary": "s", **more}


class Placing(unittest.TestCase):
    """Every lane's findings in one review: one thread per place in the
    code, whichever lanes found it."""

    LINES = {"a.py": {n: 0 for n in range(1, 21)}}

    def test_lanes_on_the_same_lines_share_a_thread(self) -> None:
        placed = g.place_findings(
            [outcome("x", at("a.py", 3, 5)), outcome("y", at("a.py", 5, 6, "high"), at("a.py", 15, 15))], self.LINES, [])
        self.assertEqual([[m["lane"] for _, m in t["members"]] for t in placed.threads], [["y", "x"], ["y"]])
        lead = g.posted_finding(placed.threads[0]["comment"]["body"])
        self.assertEqual((lead["model"], lead["severity"]), ("y-model", "high"))
        replies = g.thread_replies(placed.threads[0]["members"])
        self.assertEqual([g.posted_finding(r)["model"] for r in replies], ["x-model"])

    def test_outside_the_diff_and_open_threads(self) -> None:
        open_thread = {"path": "a.py", "line": 8, "startLine": 7, "all": [{"databaseId": 1}], "id": "T"}
        placed = g.place_findings([outcome("x", at("a.py", 30, 31), at("a.py", 8, 8, also=[{"check": "d", "severity": "low", "summary": "n"}]))],
                                  self.LINES, [open_thread])
        self.assertEqual([f["line_start"] for f, _ in placed.loose], [30])
        self.assertEqual([(f["line_start"], t["id"]) for f, _, t in placed.into_open], [(8, "T")])
        self.assertEqual(placed.threads, [])

    def test_a_findings_other_checks_reply_in_its_thread(self) -> None:
        placed = g.place_findings([outcome("x", at("a.py", 2, 2, also=[{"check": "d", "severity": "low", "summary": "n"}]))],
                                  self.LINES, [])
        replies = g.thread_replies(placed.threads[0]["members"])
        self.assertEqual([g.posted_finding(r)["check"] for r in replies], ["d"])

    def test_the_body_groups_findings_by_lane_each_signed(self) -> None:
        x, y = outcome("x"), outcome("y")
        lines = g.body_blocks([(at("a.py", 1, 1), y.meta, "a.py:1"), (at("b.py", 2, 2), x.meta, "b.py:2")], [x, y])
        text = "\n".join(lines)
        self.assertLess(text.index("b.py:2"), text.index("**x-model**"))
        self.assertLess(text.index("**x-model**"), text.index("a.py:1"))
        self.assertLess(text.index("a.py:1"), text.index("**y-model**"))


class Posting(unittest.TestCase):
    """`post` with the GitHub API stubbed: one review for every lane."""

    def test_one_review_for_every_lane(self) -> None:
        root = Path(tempfile.mkdtemp())
        lanes = [{"lane": n, "provider": "p", "model": f"{n}-model"} for n in ("a", "b", "c", "d")]
        # a and b verified; d reviewed, but the verify job has nothing of it;
        # c did not run.
        for name, line in (("a", 3), ("b", 4), ("d", 9)):
            finding = {**at("x.py", line, line), "check": name}
            for stage, verified in (("lanes", False), ("verify", True)):
                if stage == "verify" and name == "d":
                    continue
                own = root / stage / name
                own.mkdir(parents=True)
                (own / "findings.jsonl").write_text(json.dumps(finding) + "\n")
                if verified:
                    (own / "verified.jsonl").write_text(json.dumps(finding) + "\n")
        calls = []

        def github(method, url, token, body=None, accept=None):  # noqa: ANN001
            calls.append((method, url, body))
            return (200, {"id": 9, "html_url": "https://review"}) if url.endswith("/reviews") else (201, {})

        args = SimpleNamespace(repo="o/r", pr=1, head_sha="h", base_sha="b", dir=[str(root / "verify"), str(root / "lanes")],
                               verify_model="v", results=str(root / "results"), dry_run=False)
        env = {"GH_TOKEN": "t", g.LANES_ENV: json.dumps(lanes)}
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(g, "compare_files", return_value=[{"filename": "x.py", "patch": "@@ -1,0 +1,5 @@\n" + "+\n" * 5}]), \
                mock.patch.object(g, "open_threads", return_value=[]), \
                mock.patch.object(g, "collapse_resolved", return_value=0), \
                mock.patch.object(g, "paged", return_value=[{"path": "x.py", "line": 3, "id": 5}]), \
                mock.patch.object(g, "github", github):
            g.cmd_post(args)
        reviews = [body for method, url, body in calls if url.endswith("/reviews")]
        self.assertEqual(len(reviews), 1)
        self.assertEqual([c["line"] for c in reviews[0]["comments"]], [3])
        self.assertEqual([m["name"] for m in g.markers(reviews[0]["body"], "lane")], ["a", "b", "c", "d"])
        replies = [body for method, url, body in calls if url.endswith("/comments/5/replies")]
        self.assertEqual([g.posted_finding(r["body"])["model"] for r in replies], ["b-model"])
        results = {n: json.loads((root / "results" / f"{n}.json").read_text()) for n in "abcd"}
        self.assertEqual([results[n]["review_url"] for n in "abcd"], ["https://review", "https://review", None, None])
        self.assertTrue(results["c"]["did_not_run"])
        self.assertEqual((results["d"]["withheld"], results["d"]["did_not_run"]), (1, False))
        self.assertEqual(results["b"]["found"], 1)
        self.assertEqual(results["b"]["verify_model"], "v")


class Described(unittest.TestCase):
    def test_answered(self) -> None:
        f = g.answered_finding(g.comment_body(VERIFIED, META))
        self.assertEqual(
            g.described(f),
            "[medium · security] What is wrong --> and why.\n\nThe fix: 100% of it. "
            "Verified: a pull request from a fork (src/x--y.rs:120)",
        )
        self.assertEqual(g.described({"summary": "Old text."}), "Old text.")


if __name__ == "__main__":
    unittest.main()
