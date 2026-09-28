# goose-review

An LLM review of your pull requests with [Goose](https://github.com/block/goose),
where everything the review looks for is yours: your checks, your facts,
your models. One model reviews, a model of another family verifies every
finding against the code, and only confirmed findings are posted, as
comments on the lines they are about. It is advisory: it never blocks a
merge.

It was built for [NotedThat](https://github.com/NotedThat/NotedThat) (PR
#207) and extracted to be used anywhere.

## What you compose

| Piece | Where (default) | What it is |
|---|---|---|
| **Checks** | `.agents/checks/*.md` | One review type each: security, correctness, your API contract... A check runs only when the PR changes a file its `paths` match, and sees only that part of the diff. |
| **Facts** | `.agents/facts/*.md` | Things models got wrong about your stack, given to the checks and the verifier when the PR touches their `paths`. Optional. |
| **Providers** | `.github/goose/providers/*.json` | Goose provider templates: which endpoint, which models, which key. |
| **Lanes** | your workflow | Each lane: a reviewing model, a verifying model (another family), optionally a backup verifier and a subset of the checks. |

Plus, optionally, the paths never reviewed (`ignore`), tool hints for your
stack (`tools-file`), and your own rules to replace the built-in "Only
failures that can happen" (`rules-file`).

## Two ways to use it

### 1. The pre-composed workflow (start here)

`.github/workflows/goose-review.yml` in your repository. See
[`examples/caller.yml`](examples/caller.yml) for the full example:

```yaml
on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review]

concurrency:
  group: goose-review-${{ github.event.pull_request.number }}
  cancel-in-progress: false   # a push never cancels a review in progress

permissions: {}

jobs:
  goose-review:
    if: github.event.pull_request.head.repo.full_name == github.repository && !github.event.pull_request.draft
    uses: StephanMeijer/goose-review/.github/workflows/review.yml@0000000000000000000000000000000000000000 # vX.Y.Z
    permissions: { contents: read, actions: read, issues: write, pull-requests: write }
    with:
      lanes: >-
        [{"lane": "deepseek", "provider": "my_proxy", "model": "deepseek-v4-flash",
          "verify-provider": "my_proxy", "verify-model": "MiniMax-M3"}]
      egress-endpoints: |
        llm-proxy.example.com:443
    secrets:
      PROVIDER_ROUTES: ${{ secrets.GOOSE_REVIEW_ROUTES }}
      PROVIDER_ENV: ${{ secrets.GOOSE_REVIEW_PROVIDER_ENV }}
```

Pin the workflow by a release's commit SHA; the tag is in the comment.
The workflow pins its own actions to the code of that commit, so the SHA
pins everything it runs.

Inputs:
- `lanes` (required): a JSON list. Each lane is `{lane, provider, model,
  verify-provider, verify-model, verify-backup-provider?,
  verify-backup-model?, checks?, jobs?}`.
- Directories: `checks-dir`, `facts-dir`, `providers-dir`.
- Prompt and diff: `ignore`, `tools-file`, `rules-file`.
- Time budgets: `budget-minutes` (35) and `verify-budget-minutes` (12).
- The review job: `egress-endpoints` (hosts it may reach beyond GitHub),
  `setup` (your preparation, e.g. `cargo fetch --locked`), `runs-on`,
  `review-timeout-minutes` (60).

Secrets:
- `PROVIDER_ROUTES`: `<template>=<url>` lines.
- `PROVIDER_ENV`: `NAME=value` lines.

### 2. The composite actions (your own wiring)

`tidy`, `review`, `post` and `summary` are what the workflow is made of;
[`examples/hand-wired/`](examples/hand-wired/) wires them by hand.

- `tidy` first: it collapses the review's own resolved threads and marks
  the run as running.
- Then per lane, `review` in one job and `post` in another. Keep those job
  names: the summary links each lane's row to them.
- `summary` last.

Each action's inputs are documented in its `action.yml`.

## How a run goes

1. **tidy**: collapses the review's own resolved threads as outdated, and
   marks the run as running in the summary comment.
2. **review**, per lane, in a job with a read-only token and its network
   blocked (harden-runner) except for GitHub and your providers:
   1. Install Goose, plus ripgrep, fd and ast-grep (all pinned by sha256).
   2. Install your provider templates and ask each provider for its models
      (preflight).
   3. Collect the PR text and the findings someone already answered on this
      PR.
   4. Run each matching check as its own `goose run` with a shell in the
      checkout, within the time budget.
   5. Have the verifier (or its backup) re-check every finding. It must
      quote the line that shows the defect; a finding that repeats an
      answered one is rejected, unless the code the answer relied on
      changed.
   6. Scrub the provider secrets from everything, and upload it.
3. **post**, per lane, in a job that runs no model:
   1. Scrub again: once the model has had a shell in the review job,
      nothing later in that job is trusted.
   2. Post one review with the findings on their lines, as
      `github-actions[bot]` and signed with the models. A finding on lines
      with an open thread goes into that thread as a reply.
4. **summary**: one comment, always the pull request's last item:
   - the latest run on top, per model: Verified by, Checks, Found (what the
     model raised) and Posted (what a second model confirmed, with the
     rejected, already-answered and withheld counts), Result, and links to
     the jobs;
   - every earlier run folded under "All runs";
   - per model, how its threads were answered.

A push never cancels a run in progress. The newest push waits, and pushes
in between are skipped; every run reviews the whole diff. Each finding asks
whoever addresses it to reply in its thread, naming the fixing commit or
saying why it does not apply, then resolve it. Those replies are what
keeps the next run from raising the same finding again.

## Checks and facts

A check is Markdown with a flat frontmatter; `paths` is an inline JSON
list of globs, where `**/` spans directories:

```markdown
---
name: correctness
turn-limit: 40
paths: ["src/**", "lib/**"]
---

You review a pull request for bugs: changed behaviour that is demonstrably
wrong. Report only when you can state the trigger, the contract it breaks
and the symptom. ...
```

The engine adds the rest of the prompt:
- the rules ("Only failures that can happen", or your `rules-file`);
- the matching facts;
- the tools, with your `tools-file`;
- the output format;
- the diff of the files the check covers.

Facts use the same format. See [`examples/checks/`](examples/checks/) and
[`examples/facts/`](examples/facts/).

## Providers

Two kinds of Goose provider template ([`examples/providers/`](examples/providers/)):

- **Routed:** `base_url` and `base_path` carry `example.invalid`
  placeholders, and a `PROVIDER_ROUTES` line `my_proxy=https://proxy.example/route`
  fills them in. Use this for an egress proxy whose address stays out of
  your repository. A route must be `http(s)://host[:port]` plus plain path
  segments, nothing else.
- **Direct:** the template is used as written (e.g. OpenRouter).

Either way, `api_key_env` names the variable holding the key, and
`PROVIDER_ENV` has the line `NAME=value`. Only the Goose process gets
these.

Two settings are load-bearing for OpenAI-compatible endpoints:
- Set `request_params.max_tokens` (e.g. 16384): Goose otherwise asks for
  up to 384,000 output tokens, and an endpoint that counts prompt plus
  `max_tokens` against the model's length rejects the request.
- Set `context_limit` to the model's length minus `max_tokens`: Goose
  compacts a long conversation at 80% of it.

## Security model

- **The review job:** the model runs there with a shell, a read-only
  token, the network blocked except for what you list, and no sudo. Its
  environment has no GitHub token, no Actions runtime token and no raw
  provider settings, only the keys your templates name. The model's shell
  can read those keys; keep them scoped and spending-capped.
- **Once the model has run:** nothing later in the review job is trusted.
  The model can rewrite files, and through the runner's file commands
  influence later steps.
- **The post job** runs on a fresh runner with this action's own copy of
  the engine, not your checkout. It scrubs the findings again (every
  route, its origin and host, every key; verbatim, base64, hex,
  percent-encoded, reversed) before posting.
- **What remains:**
  - The review job's artifact (findings and transcripts, kept 14 days) is
    only as clean as that job.
  - A secret disguised some other way is not caught by any scrub.

  Run the review only on same-repository pull requests; the example gates
  on that.
- **Your code:** a pull request cannot change the reviewer. The engine
  comes from the pinned action, and the prompts mark the PR's text as
  untrusted data.

## Running it locally

```sh
export GOOSE_REVIEW_PROVIDER_ENV='MY_PROXY_TOKEN=...'
export GOOSE_REVIEW_PROVIDER_ROUTES='my_proxy=https://proxy.example/route'
./setup-providers.sh .github/goose/providers "${XDG_CONFIG_HOME:-$HOME/.config}/goose/custom_providers"

python3 goose_review.py review --base origin/main --provider my_proxy --model deepseek-v4-flash
python3 goose_review.py verify --base origin/main --provider my_proxy --model MiniMax-M3

# The review a lane would post, without posting it
GH_TOKEN=$(gh auth token) python3 goose_review.py post --dry-run --repo owner/repo --pr 123 \
  --head-sha "$(git rev-parse HEAD)" --base-sha "$(git rev-parse origin/main)" \
  --lane deepseek --model deepseek-v4-flash
```

Run these from your repository, calling this repository's `goose_review.py`.
Set `GOOSE_REVIEW_LOG_DIR` to keep every run's full transcript.

## Development

- `python3 -m unittest discover -s tests`: unit tests, and the engine end
  to end with `tests/fake-goose`.
- CI runs those tests, plus shellcheck, actionlint and
  `scripts/check-pins.sh`.
- `e2e.yml` and `e2e-hand-wired.yml` run both layers on the fixture pull
  requests (#1, #2) and read them back.
- After changing the actions or the engine, commit, then run
  `scripts/pin.sh` and commit the pin.
- To release: `scripts/release.sh X.Y.Z`.

Licensed under the Mozilla Public License 2.0 (see LICENSE), like NotedThat, where it began.
