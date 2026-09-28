"""What the caller composes: checks, facts, ignored paths, prompt additions,
provider settings and their redaction, and the GitHub endpoints.
Run: python3 -m unittest discover -s tests"""

import argparse
import base64
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import goose_review as g  # noqa: E402


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def check_file(name: str, paths: str = "[]") -> str:
    return f"---\nname: {name}\npaths: {paths}\n---\n\nThe {name} check.\n"


def options(**overrides: object) -> argparse.Namespace:
    values = {"checks_dir": ".agents/checks", "check": None, "facts_dir": ".agents/facts",
              "ignore": None, "tools_file": None, "rules_file": None}
    return argparse.Namespace(**{**values, **overrides})


class ConfigTest(unittest.TestCase):
    def setUp(self) -> None:
        self.saved = g.CONFIG
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        g.CONFIG = self.saved


class Checks(ConfigTest):
    def setUp(self) -> None:
        super().setUp()
        for name in ("security", "correctness", "style"):
            write(self.tmp / "checks" / f"{name}.md", check_file(name))

    def test_every_check_by_default(self) -> None:
        g.configure(options(checks_dir=str(self.tmp / "checks")))
        self.assertEqual([c.name for c in g.selected_checks()], ["correctness", "security", "style"])

    def test_only_the_named_checks(self) -> None:
        g.configure(options(checks_dir=str(self.tmp / "checks"), check=["security", " style "]))
        self.assertEqual([c.name for c in g.selected_checks()], ["security", "style"])

    def test_an_unknown_name_is_an_error(self) -> None:
        g.configure(options(checks_dir=str(self.tmp / "checks"), check=["securty"]))
        with self.assertRaisesRegex(SystemExit, "no such check .*: securty"):
            g.selected_checks()

    def test_a_missing_directory_is_an_error(self) -> None:
        g.configure(options(checks_dir=str(self.tmp / "nowhere")))
        with self.assertRaisesRegex(SystemExit, "no such checks directory"):
            g.selected_checks()


class Facts(ConfigTest):
    def test_a_missing_directory_means_no_facts(self) -> None:
        g.configure(options(facts_dir=str(self.tmp / "nowhere")))
        self.assertEqual(g.facts_section(["src/a.rs"]), "")

    def test_only_facts_whose_paths_match(self) -> None:
        write(self.tmp / "facts" / "actions.md", check_file("actions", '[".github/**"]'))
        write(self.tmp / "facts" / "rust.md", check_file("rust", '["**/*.rs"]'))
        g.configure(options(facts_dir=str(self.tmp / "facts")))
        section = g.facts_section([".github/workflows/ci.yml"])
        self.assertIn("## Facts: actions", section)
        self.assertNotIn("rust", section)


class Prompts(ConfigTest):
    def test_default_rules_and_tools(self) -> None:
        g.configure(options())
        self.assertEqual(g.rules_prompt(), g.REALISTIC_TRIGGER)
        self.assertEqual(g.tools_prompt("abc123"), g.TOOLS.format(base="abc123"))

    def test_rules_file_replaces_and_tools_file_appends(self) -> None:
        rules = write(self.tmp / "rules.md", "## Our rules\n\nOnly real bugs.\n")
        tools = write(self.tmp / "tools.md", "- Rust: `cargo tree --offline`\n")
        g.configure(options(rules_file=str(rules), tools_file=str(tools)))
        self.assertEqual(g.rules_prompt(), "## Our rules\n\nOnly real bugs.\n")
        self.assertNotIn("Only failures that can happen", g.rules_prompt())
        prompt = g.tools_prompt("abc123")
        self.assertTrue(prompt.startswith(g.TOOLS.format(base="abc123")))
        self.assertTrue(prompt.rstrip().endswith("`cargo tree --offline`"))

    def test_the_generic_prompts_name_no_project(self) -> None:
        for text in (g.TOOLS, g.VERIFY_PROMPT, g.REALISTIC_TRIGGER, g.__doc__ or ""):
            for word in ("NotedThat", "notedthat", "crates/", "SPECIFICATIONS.md", "cargo"):
                self.assertNotIn(word, text)


class Ignore(ConfigTest):
    def test_ignored_globs_leave_the_diff(self) -> None:
        repo = self.tmp / "repo"

        def git(*args: str) -> None:
            subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)

        repo.mkdir()
        git("init", "-q", "-b", "main")
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base")
        write(repo / "src" / "a.py", "x = 1\n")
        write(repo / "Cargo.lock", "lock\n")
        write(repo / "gen" / "b.py", "y = 2\n")
        git("add", "-A")
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "change")
        g.configure(options(ignore=["**/Cargo.lock", "gen/**"]))
        cwd = os.getcwd()
        try:
            os.chdir(repo)
            files = [path for path, _ in g.diff_files(g.git_diff("HEAD~1"))]
        finally:
            os.chdir(cwd)
        self.assertEqual(files, ["src/a.py"])


class Secrets(unittest.TestCase):
    ROUTE = "https://proxy.example.net/route"
    ENV = {
        "GOOSE_REVIEW_PROVIDER_ROUTES": f"acme= {ROUTE}/ \n",
        "GOOSE_REVIEW_PROVIDER_ENV": "ACME_KEY=sk-0123456789abcdef\n\nOTHER_KEY = tok-fedcba9876543210\n",
        "GOOSE_REVIEW_SECRETS": "extra-secret-value\n",
    }

    def test_every_setting_and_its_forms_are_redacted(self) -> None:
        key = "sk-0123456789abcdef"
        text = " | ".join([
            self.ROUTE, "proxy.example.net", "https://proxy.example.net", key, "tok-fedcba9876543210",
            "extra-secret-value", base64.b64encode(key.encode()).decode(), key.encode().hex(),
            urllib.parse.quote(self.ROUTE, safe=""), key[::-1],
        ])
        with mock.patch.dict(os.environ, self.ENV):
            redacted = g.redact(text)
        self.assertEqual(set(redacted.split(" | ")), {"[redacted]"})

    def test_goose_gets_the_provider_environment_only(self) -> None:
        env = {**self.ENV, "GITHUB_TOKEN": "ghs_x", "ACTIONS_RUNTIME_TOKEN": "y", "GITHUB_ENV": "/tmp/env", "KEEP": "1"}
        with mock.patch.dict(os.environ, env, clear=True):
            goose = g.goose_env("/tmp/data")
        self.assertEqual(goose["ACME_KEY"], "sk-0123456789abcdef")
        self.assertEqual(goose["OTHER_KEY"], "tok-fedcba9876543210")
        self.assertEqual(goose["KEEP"], "1")
        self.assertEqual(goose["XDG_DATA_HOME"], "/tmp/data")
        for name in ("GITHUB_TOKEN", "ACTIONS_RUNTIME_TOKEN", "GITHUB_ENV", *g.GOOSE_REVIEW_ENVS):
            self.assertNotIn(name, goose)

    def test_a_line_without_a_name_is_an_error(self) -> None:
        with self.assertRaisesRegex(SystemExit, "not a `name=value` line"):
            g.pairs("just-a-value\n")


class GitHubEndpoints(unittest.TestCase):
    def test_api_url_from_the_environment(self) -> None:
        seen = []

        class Response:
            status = 200

            def __enter__(self) -> "Response":
                return self

            def __exit__(self, *args: object) -> None:
                pass

            def read(self) -> bytes:
                return b"{}"

        def urlopen(request, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
            seen.append(request.full_url)
            return Response()

        with mock.patch.dict(os.environ, {"GITHUB_API_URL": "https://ghe.example/api/v3"}), \
                mock.patch.object(g.urllib.request, "urlopen", urlopen):
            g.github("GET", "/repos/o/r", "t")
        self.assertEqual(seen, ["https://ghe.example/api/v3/repos/o/r"])

    def test_job_names_nested_or_not(self) -> None:
        self.assertEqual(g.job_lane("deepseek / review"), ("deepseek", "review"))
        self.assertEqual(g.job_lane("goose-review / lanes / deepseek / post"), ("deepseek", "post"))
        self.assertEqual(g.job_lane("tidy"), ("", ""))
        self.assertEqual(g.job_lane("goose-review / 3 deepseek / review"), ("deepseek", "review"))
        self.assertEqual(g.job_lane("goose-review / 3 deepseek / review → post"), ("deepseek", "post"))
        self.assertNotIn(g.job_lane("goose-review / 2 tidy")[1], ("review", "post"))


class Providers(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.src = self.tmp / "providers"
        write(self.src / "routed.json", json.dumps({
            "name": "routed", "engine": "openai", "api_key_env": "ROUTED_KEY",
            "base_url": "https://example.invalid", "base_path": "example.invalid/chat/completions",
            "models": [{"name": "m"}], "requires_auth": True,
        }))
        write(self.src / "direct.json", json.dumps({
            "name": "direct", "engine": "openai", "api_key_env": "DIRECT_KEY",
            "base_url": "https://llm.example.com", "base_path": "api/v1/chat/completions",
            "models": [{"name": "m"}], "requires_auth": True,
        }))

    def setup(self, routes: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(ROOT / "setup-providers.sh"), str(self.src), str(self.tmp / "out")],
            env={**os.environ, "GOOSE_REVIEW_PROVIDER_ROUTES": routes}, capture_output=True, text=True,
        )

    def test_routed_rendered_and_direct_as_written(self) -> None:
        done = self.setup("routed=https://proxy.example.net/r1\n")
        self.assertEqual(done.returncode, 0, done.stderr)
        routed = json.loads((self.tmp / "out" / "routed.json").read_text())
        self.assertEqual((routed["base_url"], routed["base_path"]), ("https://proxy.example.net", "/r1/chat/completions"))
        self.assertEqual(json.loads((self.tmp / "out" / "direct.json").read_text())["base_url"], "https://llm.example.com")
        self.assertNotIn("proxy.example.net", done.stdout + done.stderr)

    def test_a_placeholder_without_a_route_is_an_error(self) -> None:
        done = self.setup("")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("routed has an example.invalid placeholder", done.stderr)

    def test_a_route_for_no_template_is_an_error(self) -> None:
        done = self.setup("routed=https://proxy.example.net/r1\nmissing=https://proxy.example.net/r2\n")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("'missing'", done.stderr)
        self.assertNotIn("proxy.example.net", done.stderr)

    def test_models_url(self) -> None:
        self.assertEqual(g.models_url({"base_url": "https://p.net", "base_path": "/r1/chat/completions"}), "https://p.net/r1/models")
        self.assertEqual(g.models_url({"base_url": "https://o.ai/", "base_path": "api/v1/chat/completions"}), "https://o.ai/api/v1/models")


class Preflight(unittest.TestCase):
    """Against a local server: a provider that answers, one that refuses
    the key, and one whose key is missing."""

    def setUp(self) -> None:
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                ok = self.path == "/r1/models" and self.headers.get("Authorization") == "Bearer good-key-123"
                self.send_response(200 if ok else 401)
                self.end_headers()

            def log_message(self, *args: object) -> None:
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.tmp = Path(tempfile.mkdtemp())
        write(self.tmp / "goose" / "custom_providers" / "p.json", json.dumps({
            "name": "p", "api_key_env": "P_KEY", "requires_auth": True,
            "base_url": f"http://127.0.0.1:{self.server.server_port}", "base_path": "/r1/chat/completions",
        }))
        self.status = self.tmp / "review" / "status.json"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def run_preflight(self, key: str | None) -> None:
        env = {"XDG_CONFIG_HOME": str(self.tmp), "GOOSE_REVIEW_PROVIDER_ENV": f"P_KEY={key}" if key else ""}
        with mock.patch.dict(os.environ, env):
            g.cmd_preflight(argparse.Namespace(provider=["p", "p", ""], status=str(self.status)))

    def test_answers(self) -> None:
        self.run_preflight("good-key-123")
        self.assertFalse(self.status.exists())

    def test_refused_key(self) -> None:
        with self.assertRaises(SystemExit):
            self.run_preflight("bad-key-456")
        self.assertEqual(json.loads(self.status.read_text())["error"], "the p provider answered HTTP 401")

    def test_missing_key(self) -> None:
        with self.assertRaises(SystemExit):
            self.run_preflight(None)
        self.assertIn("P_KEY is not in provider-env", json.loads(self.status.read_text())["error"])

    def test_not_configured(self) -> None:
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.tmp)}), self.assertRaises(SystemExit):
            g.cmd_preflight(argparse.Namespace(provider=["nope"], status=str(self.status)))
        self.assertIn("nope provider is not configured", json.loads(self.status.read_text())["error"])


if __name__ == "__main__":
    unittest.main()
