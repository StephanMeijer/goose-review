# Plan: extract the Goose review into `StephanMeijer/goose-review`

## Context

NotedThat PR 207 was merged into `main` as `9ea74f7` on 2026-09-27. NotedThat now runs an LLM PR review on Goose, made of:
- the engine `.github/scripts/goose_review.py` (about 2,300 lines, stdlib Python; subcommands `review`, `verify`, `answered`, `post`, `tidy`, `summary`, `scrub`);
- its tests `.github/scripts/test_goose_review.py` (unittest);
- the render script `.github/scripts/goose-render-provider.sh`;
- two workflows: `goose-review.yml` (runs `tidy`, the lane matrix, then `summary`) and `goose-review-lane.yml` (a `review` job, then a `post` job);
- the repo's own content: checks in `.agents/checks/`, facts in `.agents/facts/`, and provider templates in `.github/goose/providers/`.

The goal is to reuse this across GitHub orgs from a public repo, `github.com/StephanMeijer/goose-review`. The action is the engine only; everything the review looks for stays with the user:
- **Checks:** the check files in a configured directory (default `.agents/checks`), optionally only named ones.
- **Facts:** facts files, which use the same frontmatter as checks and whose `paths` pick the files they apply to, from a configured directory (default `.agents/facts`).
- **Providers:** Goose provider templates, from a configured directory (default `.github/goose/providers`).
- **Lanes:** entirely user-defined. Each lane names a reviewer, a verifier and an optional backup verifier.

The engine runs from a pinned action, so a PR can no longer change the reviewer's code.

**Scope:** NotedThat `main` keeps its in-repo copy for now. Moving it onto the action is a separate PR once `v0.1.0` exists; see the last section.

## Two layers

1. **Pre-composed reusable workflow** `.github/workflows/review.yml` is the default entry point. A consumer's caller is about 25 lines: `uses: StephanMeijer/goose-review/.github/workflows/review.yml@<sha>` plus inputs and secrets. Inside, it runs:
   - `tidy`;
   - the lane matrix from `fromJSON(inputs.lanes)`, where each lane calls the internal reusable `lane.yml` (a `review` job, then a `post` job);
   - `summary`, with `needs: [tidy, lanes]`.

   Every job starts with harden-runner.
2. **Composite actions** (`tidy`, `review`, `post`, `summary`) are what the workflow uses. Repos that need different wiring call them directly.

**Internal refs.** Inside `review.yml` and `lane.yml`, the `uses:` lines for the composite actions must be fixed strings. `scripts/release.sh <version>` rewrites them to the release commit's SHA, commits, tags `v<version>`, and moves `v0`. CI fails if an internal ref points anywhere other than a commit reachable from the tag being built. Pinning the workflow by SHA therefore pins the actions and the engine too.

## Configuration

### Lane fields

`lanes` is JSON for the workflow, or matching inputs on the `review`/`post` actions:
- `lane`: `[a-z0-9-]+`.
- `provider`, `model`: the reviewer.
- `verify-provider`, `verify-model`: the verifier.
- `verify-backup-provider`, `verify-backup-model`: optional. They verify when the verifier's provider answers empty or with no verdicts; this is on `main` since `1774786` and `798c2e4`.
- `checks`: optional subset of check names.
- `jobs`: checks run at once (default 2).

### Content and prompts

These are inputs on both the workflow and the `review` action:

| Input | Default | Purpose |
|---|---|---|
| `checks-dir` | `.agents/checks` | Where the check files are (replaces `CHECKS_DIR`) |
| `facts-dir` | `.agents/facts` | Where the facts files are (replaces `FACTS_DIR`, line 44); a missing directory means no facts |
| `providers-dir` | `.github/goose/providers` | Where the provider templates are |
| `ignore` | none | Newline-separated globs excluded from the diff (replaces `IGNORED_PATHSPECS`) |
| `tools-file` | none | Appended to a generic `TOOLS` prompt (NotedThat's Rust, cargo and ast-grep hints move into its own file) |
| `rules-file` | built-in `REALISTIC_TRIGGER` ("Only failures that can happen") | Replaces the rules added to every check's and the verifier's prompt |
| `budget-minutes`, `verify-budget-minutes` | 35, 12 | Time budgets |

### Providers and secrets (generalises NotedThat's proxy and OpenRouter wiring)

Two secrets, each multiline:
- **`provider-routes`:** `<template name>=<url>`. Each line renders that template via the render script:
  - the strict route shape from `8d12957` is kept;
  - origin goes into `base_url`, path into `base_path`;
  - `--check` preflights the route at `GET <url>/models`.
- **`provider-env`:** `NAME=value`. Passed to Goose only in the review and verify steps; templates point `api_key_env` at a NAME.
  - A template without a route is used as written. This is the OpenRouter case: a direct `base_url`, and its key in `provider-env`.

Every route (with its origin and host) and every `provider-env` value goes into `GOOSE_REVIEW_SECRETS`. That env var replaces `NOTEDTHAT_PROXY_TOKEN`, `OPENROUTER_API_KEY` and `ROUTE_ENVS` in `proxy_secrets()` (line 904), and it drives both scrubs.

`egress-endpoints` (workflow input) adds hosts to the review job's allow-list, for example the proxy host or `openrouter.ai:443`. NotedThat currently derives these per lane (`USES_OPENROUTER`, lane.yml:64); in the action the caller lists them.

Provider-specific preflights such as NotedThat's OpenRouter credit check (lane.yml:172) belong in the caller's `setup` input, not in the engine.

### Job settings (workflow only)

- `setup`: shell commands run after checkout, before any secret or model (for example `cargo fetch --locked`).
- `runs-on` (default `ubuntu-latest`) and `review-timeout-minutes` (default 60).
- Goose `v1.52.0` and the sha256-pinned rg, fd and ast-grep are defaults of the `review` action. `install-goose: false` lets CI supply a fake goose.

### Tokens

- `github-token` is used only by `answered`, `post`, `tidy` and `summary`, never in the review or verify steps. `GITHUB_TOKENS`, `ACTIONS_*` and `FILE_COMMANDS` stay stripped from the model's environment.
- `summary` needs `actions: read`, `issues: write` and `pull-requests: write`.

The same-repo/draft/release gate and the concurrency group (`cancel-in-progress: false`) stay in the caller, and the example shows them.

## Repo layout (new, public, MPL-2.0)

```
.github/workflows/review.yml   pre-composed reusable workflow (entry point)
.github/workflows/lane.yml     internal: `review` then `post` for one lane
.github/workflows/ci.yml
goose_review.py                engine (from NotedThat main, generalised)
render-provider.sh             from goose-render-provider.sh (strict route shape, --check)
review/ post/ tidy/ summary/   composite actions (action.yml each); they run
                               python3 "$GITHUB_ACTION_PATH/../goose_review.py"
scripts/release.sh
tests/test_goose_review.py     ported from NotedThat, then extended
tests/fake-goose               canned `--output-format json` answers for e2e
examples/caller.yml            ~25-line caller of review.yml (the main example)
examples/hand-wired/           goose-review.yml + goose-review-lane.yml calling the actions
examples/checks/example.md, examples/facts/example.md, examples/providers/{routed,direct}.json
README.md, LICENSE, CHANGELOG.md
```

## Engine changes (from NotedThat `main` at `9ea74f7`)

These are flags on `review`/`verify`; the actions pass them through:
- `--checks-dir` and repeatable `--check NAME`: filter checks in `load_checks`.
- `--facts-dir`: `facts_section` (line 356) reads from it; a missing directory means no facts.
- Repeatable `--ignore GLOB`: must reach `verify` too, because it re-diffs.
- `--tools-file` and `--rules-file`.

Secrets and tokens:
- `proxy_secrets()` reads `GOOSE_REVIEW_SECRETS`.
- `NOTEDTHAT_PROXY_TOKEN` is renamed. Templates name their own `api_key_env`, so the engine no longer needs to know any key's name.

Prompt text:
- `TOOLS` becomes generic, with no crate paths.
- `SPECIFICATIONS.md` in `VERIFY_PROMPT` and the docstring becomes "the repository's documentation and specifications". The facts mechanism is the way to point models at specific docs.

GitHub URLs and job names:
- `GITHUB_API_URL` and `GITHUB_SERVER_URL` replace the hard-coded `api.github.com` and `github.com`.
- `summary` matches jobs on the last two ` / ` parts of the name (lane and kind). That covers both `lanes / deepseek / review` inside the reusable workflow and `deepseek / review` in a hand-wired caller. A job that matches neither form gets a row without links.

Kept as on `main`:
- the structured markers (`MARKER_PATTERN`, `f1b5629`) and their legacy readers;
- answered findings, per model, with section limits;
- backup verification;
- open-thread merging and the collapse rule;
- the summary layout (latest run on top, "All runs" folded);
- the redaction encodings;
- the `status.json` and result formats.

## Tests and CI in the new repo

- **Unit tests:** port `test_goose_review.py` (RoundTrip, Broken, Legacy, MissingPatch, Small, Described) as is, then add tests for:
  - `--checks-dir`, `--check` and `--facts-dir` selection;
  - `--ignore` in both `review` and `verify`;
  - `GOOSE_REVIEW_SECRETS` redaction, including percent, base64 and hex forms;
  - route-less templates;
  - `summary` job-name matching in both forms;
  - `rules-file` replacing `REALISTIC_TRIGGER`.
- **CI (`ci.yml`):**
  - `python -m py_compile`, `python -m unittest`, `actionlint` and `shellcheck`;
  - a check that the internal refs are pinned.
- **E2E:** on a fixture branch and PR in the repo itself, with `install-goose: false` and `tests/fake-goose`:
  - through the composite actions, hand-wired;
  - through `review.yml`.

  It asserts that findings are posted inline, that a second run on the same lines replies in the open thread, that the summary is the last comment, and that the backup verifier is used when the fake verifier answers empty.
- **Release:** `scripts/release.sh 0.1.0`. The README tells consumers to pin by SHA.

## README

Covers:
- the layers;
- how checks, facts, providers and lanes compose, including the backup verifier;
- the check and facts file formats, and both provider template kinds (routed and direct);
- the load-bearing `max_tokens` and `context_limit` settings;
- the security model: the review job is untrusted once the model has a shell, `post` scrubs again on a fresh runner, and the artifact risk remains;
- running locally (from NotedThat DEVELOPMENT.md);
- the summary's columns.

## Order of work

1. Create the repo with `gh repo create StephanMeijer/goose-review --public` (MPL-2.0, like NotedThat), working locally under `~/Projects/github.com/StephanMeijer/goose-review`.
2. Copy the engine, tests and render script from NotedThat `main` (`9ea74f7`), confirm the ported tests pass unchanged, then make the engine changes with tests.
3. The four composite actions.
4. `review.yml`, `lane.yml`, `scripts/release.sh` and the internal-ref check.
5. Examples, then CI, then e2e on a fixture PR.
6. README, then compare against NotedThat `main` again and port any newer engine commits, then release `v0.1.0`.

## Verification

- Unit tests, `actionlint` and `shellcheck` pass locally and in CI, including the ported NotedThat tests.
- E2E with the fake goose passes through both layers, as listed above.
- Read-only against NotedThat #207 with the new engine and NotedThat's settings as inputs (checks, facts, providers, ignore list, a tools file holding the old Rust `TOOLS` text): `answered`, `tidy --dry-run`, `post --dry-run` and `summary --dry-run`. The output should match `main`'s engine.
- Real models: a throwaway NotedThat branch (not `main`) whose caller uses `review.yml@<sha>` with NotedThat's three lanes (deepseek, minimax, mistral, each with its backup) and the real secrets, run once on a small PR.

## Afterwards (separate PR in NotedThat, not in this plan's scope)

1. Replace the two workflows with `examples/caller.yml` filled in with NotedThat's settings.
2. Move the old Rust `TOOLS` text into `.agents/goose-review/tools.md`.
3. Delete `.github/scripts/goose_review.py`, its test file and the render script.
4. Map the secrets into `provider-routes` and `provider-env`.
