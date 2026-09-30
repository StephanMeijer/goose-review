"""The engine end to end with tests/fake-goose, no network: the review posts
the planted line through post_comment, the verifier confirms it with
evidence, a verifier that answers empty hands over to the backup, and with
no poster the confirmed finding waits in pending.jsonl for `post`.
Run: python3 -m unittest discover -s tests"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "goose_review.py"


class Engine(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp())
        bin_dir = self.repo / ".fakebin"
        bin_dir.mkdir()
        (bin_dir / "goose").symlink_to(ROOT / "tests" / "fake-goose")
        self.env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                    "XDG_DATA_HOME": str(self.repo / ".data")}
        self.git("init", "-q", "-b", "main")
        self.write(".agents/checks/planted.md", '---\nname: planted\npaths: ["src/**"]\n---\n\nFind planted markers.\n')
        self.write(".agents/checks/other.md", '---\nname: other\npaths: ["docs/**"]\n---\n\nNever runs here.\n')
        self.write("src/a.py", "x = 1\n")
        self.commit("base")
        self.write("src/a.py", 'x = 1\ny = "GOOSE-REVIEW-E2E here"\n')
        self.write("gen/b.py", 'z = "GOOSE-REVIEW-E2E generated"\n')
        self.commit("change")
        (self.repo / "out").mkdir()

    def write(self, path: str, text: str) -> None:
        (self.repo / path).parent.mkdir(parents=True, exist_ok=True)
        (self.repo / path).write_text(text, encoding="utf-8")

    def git(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True)

    def commit(self, message: str) -> None:
        self.git("add", "-A")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", message)

    def engine(self, *args: str, **env: str) -> subprocess.CompletedProcess:
        done = subprocess.run([sys.executable, str(ENGINE), *args], cwd=self.repo, env={**self.env, **env},
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done

    def read(self, name: str) -> list[dict]:
        return [json.loads(line) for line in (self.repo / "out" / name).read_text().splitlines() if line.strip()]

    def status(self) -> dict:
        return json.loads((self.repo / "out" / "status.json").read_text())

    def review(self, *extra: str, **env: str) -> None:
        self.engine("review", "--base", "HEAD~1", "--provider", "p", "--model", "reviewer",
                    "--verify-provider", "p", "--verify-model", "verifier",
                    "--backup-provider", "p", "--backup-model", "backup", "--ignore", "gen/**",
                    "--out", "out/pending.jsonl", "--status", "out/status.json", *extra, **env)

    def test_a_finding_is_verified_as_it_is_posted(self) -> None:
        self.review()
        pending = self.read("pending.jsonl")
        self.assertEqual([(f["path"], f["line_start"], f["check"]) for f in pending], [("src/a.py", 2, "planted")])
        self.assertEqual(pending[0]["evidence"], {"path": "src/a.py", "line": 2})
        self.assertEqual(pending[0]["verified_by"], "verifier")
        self.assertEqual([c["outcome"] for c in self.read("calls.jsonl")], ["pending"])
        status = self.status()
        self.assertEqual(status["checks_run"], ["planted"])
        self.assertEqual(status["checks_skipped"], ["other"])
        self.assertEqual(status["checks_failed"], [])
        self.assertEqual((status["found"], status["pending"], status["rejected"]), (1, 1, 0))
        self.assertEqual(status["verified_by"], ["verifier"])

    def test_the_backup_verifies_when_the_verifier_answers_empty(self) -> None:
        self.review(FAKE_GOOSE_EMPTY_MODELS="verifier")
        self.assertEqual([f.get("verified_by") for f in self.read("pending.jsonl")], ["backup"])
        self.assertEqual(self.status()["verified_by"], ["backup"])

    def test_only_the_named_checks_run(self) -> None:
        self.review("--check", "other")
        self.assertEqual(self.read("pending.jsonl"), [])
        self.assertEqual(self.status()["checks_run"], [])
        self.assertEqual(self.status()["found"], 0)


if __name__ == "__main__":
    unittest.main()
