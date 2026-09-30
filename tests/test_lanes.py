"""The caller's lanes: the YAML subset they are written in, JSON as before,
and the checks that turn a typo into an error before any lane runs.
Run: python3 -m unittest discover -s tests"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import goose_review as g  # noqa: E402

YAML = """
# NotedThat's lanes
- lane: deepseek
  provider: notedthat_thirdparty
  model: deepseek-v4-flash-0731   # the third-party endpoint
  jobs: 2

- lane: minimax
  provider: notedthat_minimax
  model: 'MiniMax-M3'
  checks: [security, correctness]
-
  lane: mistral
  provider: "notedthat_thirdparty"
  model: mistral-medium-3-5
  checks:
  - security
  -   correctness
"""

FIRST = {"lane": "deepseek", "provider": "notedthat_thirdparty", "model": "deepseek-v4-flash-0731", "checks": [], "jobs": 2}
ONE = "  provider: p\n  model: m\n"


def lanes(text: str, **known: list[str]) -> list[dict]:
    return g.validate_lanes(g.parse_lanes(text), known.get("checks"), known.get("providers"))


class Parse(unittest.TestCase):
    def test_yaml(self) -> None:
        got = lanes(YAML)
        self.assertEqual(got[0], FIRST)
        self.assertEqual(got[1]["checks"], ["security", "correctness"])
        self.assertEqual(got[1]["model"], "MiniMax-M3")
        self.assertEqual(got[2]["provider"], "notedthat_thirdparty")
        self.assertEqual(got[2]["checks"], ["security", "correctness"])
        self.assertEqual([lane["lane"] for lane in got], ["deepseek", "minimax", "mistral"])

    def test_json_as_before(self) -> None:
        text = json.dumps([{k: v for k, v in FIRST.items() if k != "checks"}])
        self.assertEqual(lanes(text), [FIRST])

    def test_checks_as_a_string(self) -> None:
        text = f"- lane: a\n{ONE}  checks: security, correctness\n"
        self.assertEqual(lanes(text)[0]["checks"], ["security", "correctness"])

    def test_a_hash_inside_quotes_is_no_comment(self) -> None:
        text = "- lane: a\n  provider: p # the proxy\n  model: 'm#1'\n"
        got = lanes(text)[0]
        self.assertEqual((got["model"], got["provider"]), ("m#1", "p"))


class Errors(unittest.TestCase):
    def fails(self, text: str, message: str, **known: list[str]) -> None:
        with self.assertRaisesRegex(g.LanesError, message):
            lanes(text, **known)

    def test_a_mistyped_key(self) -> None:
        self.fails(f"- lane: a\n{ONE}  job: 2\n", r"lane 1 \(a\): unknown key\(s\) job")
        # The verifier is the workflow's, no lane's.
        self.fails(f"- lane: a\n{ONE}  verify-model: v\n", r"unknown key\(s\) verify-model")

    def test_a_missing_key(self) -> None:
        self.fails("- lane: a\n  provider: p\n", "missing model")

    def test_a_bad_or_repeated_name(self) -> None:
        self.fails(f"- lane: Deep Seek\n{ONE}", r"\[a-z0-9-\]\+")
        self.fails(f"- lane: summary\n{ONE}", "not `summary`")
        self.fails(f"- lane: a\n{ONE}- lane: a\n{ONE}", "used twice")

    def test_jobs_out_of_range(self) -> None:
        self.fails(f"- lane: a\n{ONE}  jobs: 0\n", "jobs must be")

    def test_unknown_checks_and_providers(self) -> None:
        text = f"- lane: a\n{ONE}  checks: [securty]\n"
        self.fails(text, "no such check securty", checks=["security"], providers=["p"])
        self.fails(text.replace("  checks: [securty]\n", ""), "provider `p` has no template", providers=["q"])

    def test_not_the_supported_yaml(self) -> None:
        self.fails("lane: a\n", "start each lane with `- `")
        self.fails("- lane: a\n    provider: p\n", "line 2: indented unlike")
        self.fails("- lane: a\n  provider: {x: 1}\n", "line 2: not a plain value")
        self.fails("- lane: a\n  lane: b\n", "line 2: `lane` given twice")
        self.fails("[1, 2]", "a list of mappings")
        self.fails("", "no lane given")


class Verifier(unittest.TestCase):
    def test_complete(self) -> None:
        g.validate_verifier("p", "v", "q", "b", providers=["p", "q"])
        g.validate_verifier("p", "v")

    def test_errors(self) -> None:
        for args, message in (
            (("p", ""), "both required"),
            (("p", "v", "q", ""), "both verify-backup-provider and verify-backup-model"),
            (("p", "v", "q", "b"), "verify-backup-provider `q` has no template"),
        ):
            with self.subTest(args=args), self.assertRaisesRegex(g.LanesError, message):
                g.validate_verifier(*args, providers=["p"])


class Command(unittest.TestCase):
    def run_lanes(self, text: str, cwd: Path, *more: str) -> subprocess.CompletedProcess:
        output = cwd / "output"
        done = subprocess.run(
            [sys.executable, str(ROOT / "goose_review.py"), "lanes", *more], cwd=cwd, capture_output=True, text=True,
            env={**os.environ, "GOOSE_REVIEW_LANES": text, "GITHUB_OUTPUT": str(output)},
        )
        done.output = output.read_text() if output.exists() else ""
        return done

    def test_writes_the_matrix(self) -> None:
        repo = Path(tempfile.mkdtemp())
        (repo / ".agents" / "checks").mkdir(parents=True)
        for name in ("security", "correctness"):
            (repo / ".agents" / "checks" / f"{name}.md").write_text(f"---\nname: {name}\n---\n\nx\n")
        (repo / ".github" / "goose" / "providers").mkdir(parents=True)
        for name in ("notedthat_thirdparty", "notedthat_minimax"):
            (repo / ".github" / "goose" / "providers" / f"{name}.json").write_text("{}")
        verifier = ("--verify-provider", "notedthat_minimax", "--verify-model", "MiniMax-M3")
        done = self.run_lanes(YAML, repo, *verifier)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(done.output.startswith("lanes=[") and done.output.count("\n") == 1)
        self.assertEqual(json.loads(done.output[len("lanes="):])[0], FIRST)
        self.assertIn("lane minimax: MiniMax-M3 reviews; checks security, correctness", done.stderr)
        self.assertIn("MiniMax-M3 verifies every lane's findings", done.stderr)
        done = self.run_lanes(YAML, repo, "--verify-provider", "nowhere", "--verify-model", "v")
        self.assertIn("::error::verify-provider `nowhere` has no template", done.stderr)

    def test_an_error_is_annotated(self) -> None:
        done = self.run_lanes("- lane: a\n  provider: p\n", Path(tempfile.mkdtemp()))
        self.assertEqual(done.returncode, 1)
        self.assertIn("::error::lane 1 (a): missing model", done.stderr)
        self.assertEqual(done.output, "")


if __name__ == "__main__":
    unittest.main()
