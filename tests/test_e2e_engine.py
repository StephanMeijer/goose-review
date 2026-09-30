"""The engine end to end with tests/fake-goose, no network: review finds the
planted line, verify keeps it with evidence, and a verifier that answers
empty hands over to the backup; review-lanes does both for every lane at
once. Run: python3 -m unittest discover -s tests"""

import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "goose_review.py"


class Repo(unittest.TestCase):
    """A repository whose last commit adds a planted line, with the fake on PATH."""

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


class Engine(Repo):
    def review(self) -> None:
        self.engine("review", "--base", "HEAD~1", "--provider", "p", "--model", "reviewer",
                    "--ignore", "gen/**", "--out", "out/findings.jsonl", "--status", "out/status.json")

    def verify(self, **env: str) -> None:
        self.engine("verify", "--base", "HEAD~1", "--provider", "p", "--model", "verifier",
                    "--backup-provider", "p", "--backup-model", "backup", "--ignore", "gen/**",
                    "--in", "out/findings.jsonl", "--out", "out/verified.jsonl", "--status", "out/status.json", **env)

    def test_review_then_verify(self) -> None:
        self.review()
        findings = self.read("findings.jsonl")
        self.assertEqual([(f["path"], f["line_start"], f["check"]) for f in findings], [("src/a.py", 2, "planted")])
        self.assertEqual(self.status()["checks_run"], ["planted"])
        self.assertEqual(self.status()["checks_skipped"], ["other"])
        self.verify()
        verified = self.read("verified.jsonl")
        self.assertEqual(len(verified), 1)
        self.assertEqual(verified[0]["evidence"], {"path": "src/a.py", "line": 2})
        self.assertNotEqual(verified[0].get("verified_by"), "backup")

    def test_the_backup_verifies_when_the_verifier_answers_empty(self) -> None:
        self.review()
        self.verify(FAKE_GOOSE_EMPTY_MODELS="verifier")
        self.assertEqual([f.get("verified_by") for f in self.read("verified.jsonl")], ["backup"])
        self.assertEqual(self.status()["verified_by"], ["backup"])

    def test_only_the_named_checks_run(self) -> None:
        self.engine("review", "--base", "HEAD~1", "--provider", "p", "--model", "reviewer", "--check", "other",
                    "--out", "out/findings.jsonl", "--status", "out/status.json")
        self.assertEqual(self.read("findings.jsonl"), [])
        self.assertEqual(self.status()["checks_run"], [])


class Lanes(Repo):
    """review-lanes: every lane in one call, each in its own directory; a
    lane whose provider does not answer stops alone."""

    def setUp(self) -> None:
        super().setUp()
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Models)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        providers = self.repo / ".config" / "goose" / "custom_providers"
        providers.mkdir(parents=True)
        (providers / "p.json").write_text(json.dumps({
            "name": "p", "base_url": f"http://127.0.0.1:{server.server_address[1]}",
            "base_path": "chat/completions", "requires_auth": False,
        }))
        self.env["XDG_CONFIG_HOME"] = str(self.repo / ".config")

    def lanes(self, lanes: list[dict]) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(ENGINE), "review-lanes", "--base", "HEAD~1", "--out", "out", "--", "--ignore", "gen/**"],
            cwd=self.repo, env={**self.env, "GOOSE_REVIEW_LANES": json.dumps(lanes),
                                "GOOSE_REVIEW_LOG_DIR": str(self.repo / "logs")},
            capture_output=True, text=True,
        )

    def lane(self, name: str, **more: object) -> dict:
        return {"lane": name, "provider": "p", "model": f"{name}-reviewer", "verify-provider": "p",
                "verify-model": f"{name}-verifier", **more}

    def test_every_lane_reviews_and_verifies(self) -> None:
        done = self.lanes([self.lane("a"), self.lane("b", checks=["other"])])
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(len(self.read("a/verified.jsonl")), 1)
        self.assertEqual(self.read("b/verified.jsonl"), [])
        self.assertEqual(json.loads((self.repo / "out/b/status.json").read_text())["checks_run"], [])
        self.assertIn("[a] ", done.stdout)
        self.assertTrue(any((self.repo / "logs" / "a").iterdir()))

    def test_a_lane_whose_provider_is_missing_fails_alone(self) -> None:
        done = self.lanes([self.lane("a"), self.lane("b", provider="nowhere")])
        self.assertEqual(done.returncode, 1)
        self.assertEqual(len(self.read("a/verified.jsonl")), 1)
        self.assertIn("nowhere provider is not configured", json.loads((self.repo / "out/b/status.json").read_text())["error"])
        self.assertIn("::warning::b: preflight failed", done.stdout)


class Models(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"data": []}')

    def log_message(self, *args: object) -> None:
        pass


if __name__ == "__main__":
    unittest.main()
