"""The caller's tools: the same YAML subset as the lanes, the checks that
stop a run on a typo, installing one from a file or an archive by its
sha256, and the lines that announce them to the model.
Run: python3 -m unittest discover -s tests"""

import argparse
import hashlib
import io
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import goose_review as g  # noqa: E402

SHA = "0" * 64

YAML = f"""
# A chart repository's tools
- name: helm
  version: v4.1.4
  url: https://get.helm.sh/helm-v4.1.4-linux-amd64.tar.gz
  sha256: {SHA.upper()}
  path: linux-amd64/helm
  use: "Render a chart: `helm template t <chart>`."

- name: kubeconform
  url: https://github.com/yannh/kubeconform/releases/download/v0.8.0/kubeconform-linux-amd64.tar.gz
  sha256: {SHA}
  use: Validate rendered manifests against the Kubernetes schemas.
"""


def tar_gz(files: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return out.getvalue()


def zipped(files: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return out.getvalue()


def tool(name: str, url: str, data: bytes, path: str = "") -> dict:
    return {"name": name, "url": url, "sha256": hashlib.sha256(data).hexdigest(), "use": "x",
            "path": path, "version": ""}


class Parse(unittest.TestCase):
    def test_yaml(self) -> None:
        helm, kubeconform = g.parse_tools(YAML)
        self.assertEqual(helm, {
            "name": "helm", "version": "v4.1.4", "url": "https://get.helm.sh/helm-v4.1.4-linux-amd64.tar.gz",
            "sha256": SHA, "path": "linux-amd64/helm", "use": "Render a chart: `helm template t <chart>`.",
        })
        self.assertEqual((kubeconform["path"], kubeconform["version"]), ("", ""))

    def test_json_and_none(self) -> None:
        text = f'[{{"name": "jq", "url": "https://example.com/jq", "sha256": "{SHA}", "use": "Query JSON."}}]'
        self.assertEqual([t["name"] for t in g.parse_tools(text)], ["jq"])
        self.assertEqual(g.parse_tools(""), [])
        self.assertEqual(g.parse_tools("  \n"), [])


class Errors(unittest.TestCase):
    one = f"  url: https://example.com/t\n  sha256: {SHA}\n  use: x\n"

    def fails(self, text: str, message: str) -> None:
        with self.assertRaisesRegex(g.LanesError, message):
            g.parse_tools(text)

    def test_keys(self) -> None:
        self.fails(f"- name: t\n{self.one}  sha: x\n", r"tool 1 \(t\): unknown key\(s\) sha")
        self.fails("- name: t\n  url: https://example.com/t\n", "missing sha256, use")

    def test_names(self) -> None:
        self.fails(f"- name: my tool\n{self.one}", r"\[A-Za-z0-9._-\]\+")
        self.fails(f"- name: rg\n{self.one}", "not one of ast-grep, fd, git, goose")
        self.fails(f"- name: t\n{self.one}- name: t\n{self.one}", "used twice")

    def test_download(self) -> None:
        self.fails(f"- name: t\n  url: http://example.com/t\n  sha256: {SHA}\n  use: x\n", "url must be https://")
        self.fails("- name: t\n  url: https://example.com/t\n  sha256: abc\n  use: x\n", "sha256 must be 64 hex")
        self.fails(f"- name: t\n{self.one}  path: bin/t\n", "path is for an archive")
        self.fails(f"- name: t\n{self.one.replace('/t', '/t.tgz')}  path: ../t\n", "without `..`")

    def test_not_the_supported_yaml(self) -> None:
        self.fails("name: t\n", "start each tool with `- `")
        self.fails(f"- name: t\n{self.one}  name: u\n", "line 5: `name` given twice in one tool")
        self.fails("[1]", "tools: must be a list of mappings")


class Install(unittest.TestCase):
    def setUp(self) -> None:
        self.bin = Path(tempfile.mkdtemp())

    def install(self, entry: dict, data: bytes) -> bytes:
        path = g.install_tool(entry, self.bin, fetch=lambda url: data)
        self.assertEqual(path, self.bin / entry["name"])
        self.assertTrue(os.access(path, os.X_OK))
        return path.read_bytes()

    def test_a_file(self) -> None:
        self.assertEqual(self.install(tool("t", "https://example.com/t", b"#!/bin/sh\n"), b"#!/bin/sh\n"), b"#!/bin/sh\n")

    def test_a_tar_member_by_path_or_by_name(self) -> None:
        data = tar_gz({"./linux-amd64/helm": b"helm", "linux-amd64/LICENSE": b"l"})
        self.assertEqual(self.install(tool("helm", "https://x.io/h.tar.gz", data, "linux-amd64/helm"), data), b"helm")
        self.assertEqual(self.install(tool("helm", "https://x.io/h.tar.gz", data), data), b"helm")

    def test_a_zip_member(self) -> None:
        data = zipped({"ast/t": b"t", "README": b"r"})
        self.assertEqual(self.install(tool("t", "https://x.io/t.zip", data), data), b"t")

    def test_a_wrong_sha256_installs_nothing(self) -> None:
        entry = {**tool("t", "https://example.com/t", b"good"), "name": "t"}
        with self.assertRaisesRegex(g.LanesError, "has sha256 .*, not "):
            g.install_tool(entry, self.bin, fetch=lambda url: b"evil")
        self.assertFalse((self.bin / "t").exists())

    def test_a_missing_or_ambiguous_member(self) -> None:
        data = tar_gz({"a/t": b"1", "b/t": b"2"})
        with self.assertRaisesRegex(g.LanesError, "2 files named t .*give its `path`"):
            g.install_tool(tool("t", "https://x.io/t.tgz", data), self.bin, fetch=lambda url: data)
        with self.assertRaisesRegex(g.LanesError, "no file c/t in"):
            g.install_tool(tool("t", "https://x.io/t.tgz", data, "c/t"), self.bin, fetch=lambda url: data)


class Prompt(unittest.TestCase):
    def tearDown(self) -> None:
        g.CONFIG = g.Config()

    def configure(self, tools: str | None, tools_file: str | None = None) -> None:
        g.configure(argparse.Namespace(checks_dir=".agents/checks", check=None, facts_dir=".agents/facts",
                                       ignore=None, tools_file=tools_file, tools=tools, rules_file=None))

    def test_announced_after_the_tools_and_before_the_hints(self) -> None:
        hints = Path(tempfile.mkdtemp()) / "tools.md"
        hints.write_text("- Charts: `ci/` renders them.\n")
        self.configure(YAML, str(hints))
        prompt = g.tools_prompt("abc123")
        self.assertEqual(prompt, g.TOOLS.format(base="abc123") + "\n" + g.INSTALLED_TOOLS
                         + "- `helm` (v4.1.4): Render a chart: `helm template t <chart>`.\n"
                         + "- `kubeconform`: Validate rendered manifests against the Kubernetes schemas.\n"
                         + "\n- Charts: `ci/` renders them.\n")

    def test_none_announces_nothing(self) -> None:
        self.configure(None)
        self.assertEqual(g.tools_prompt("abc123"), g.TOOLS.format(base="abc123"))


class Command(unittest.TestCase):
    def run_tools(self, text: str, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(ROOT / "goose_review.py"), "tools", *args],
                              capture_output=True, text=True, env={**os.environ, "GOOSE_REVIEW_TOOLS": text})

    def test_checks_without_installing(self) -> None:
        done = self.run_tools(YAML)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("tool helm v4.1.4: Render a chart", done.stderr)

    def test_an_error_is_annotated(self) -> None:
        done = self.run_tools("- name: t\n")
        self.assertEqual(done.returncode, 1)
        self.assertIn("::error::tool 1 (t): missing url, sha256, use", done.stderr)

    def test_the_lanes_command_checks_the_tools_too(self) -> None:
        lanes = "- lane: a\n  provider: p\n  model: m\n  verify-provider: p\n  verify-model: v\n"
        done = subprocess.run([sys.executable, str(ROOT / "goose_review.py"), "lanes"], cwd=tempfile.mkdtemp(),
                              capture_output=True, text=True,
                              env={**os.environ, "GOOSE_REVIEW_LANES": lanes, "GOOSE_REVIEW_TOOLS": "- name: t\n",
                                   "GITHUB_OUTPUT": os.devnull})
        self.assertEqual(done.returncode, 1)
        self.assertIn("::error::tool 1 (t): missing url", done.stderr)


if __name__ == "__main__":
    unittest.main()
