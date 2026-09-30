# Changelog

## 0.4.0

- **Breaking:** findings are posted as they are found. The reviewer reports
  each finding through a `post_comment` tool as soon as it has established
  it; a model of another family verifies it then and there, and a confirmed
  finding is posted right away -- as a single-comment review, or a reply in
  the lane thread open on its lines. The reviewer hears back either way,
  posted or denied and why, and carries on. A finding on unchanged lines,
  or on lines already commented on, is denied without a model.
  - The review job's token can now write (`pull-requests: write`): only the
    new `poster` action holds it -- a process of its own user, started
    before harden-runner removes sudo, with the token in its memory only.
    It checks, scrubs and signs every finding before posting it. See the
    README's "Security model".
  - Hand-wired callers: put `poster` first in the review job (it also
    checks out the pull request), give harden-runner `token: ""`, drop
    `actions/checkout` there, and grant the job `pull-requests: write`.
  - The `verify` step and subcommand are gone: `review` takes
    `--verify-provider`, `--verify-model` and the backup, and writes the
    confirmed findings it could not post (`pending.jsonl`) and every call
    (`calls.jsonl`). `post` posts what is left and counts what the lane
    posted from the pull request.
  - `budget-minutes` (now 45) covers verification too;
    `verify-budget-minutes` is deprecated, and a value given is added to it.
  - The summary's Posted column counts denied findings and duplicates.
- `tools`: install your own tools in the review job and tell the model it
  may run them -- a linter, `helm`, `kubeconform`. Each is a download fixed
  by its sha256 (a binary, or one file out of an archive) with a `use` line
  the model reads. They are installed before `setup`, which can use them,
  and the `plan` job checks the list. The new `tools` action does the
  installing for hand-wired callers; the `review` action's `tools` input
  announces them.

## 0.3.2

- The workflow's jobs have their plain names again (`plan`, `tidy`,
  `<lane> / review`, `<lane> / post`, `summary`): the numbered ones of 0.3.1
  read worse. The summary still reads both.

## 0.3.1

- The pre-composed workflow's jobs are numbered by stage (`1 plan`, `2 tidy`,
  `3 <lane> / review`, `3 <lane> / review → post`, `4 summary`), so a checks
  list sorted by name shows them in the order they run. The summary reads
  both these names and the plain ones of a hand-wired caller.

## 0.3.0

- `lanes` may be YAML: a list of mappings, one key per line, with comments.
  JSON still works.
- A `plan` job (the new `lanes` action) checks the lanes before any lane
  runs, and stops the run with the errors shown: an unknown or missing key,
  a bad or repeated name, half a backup verifier, `jobs` out of range, a
  check or provider template that does not exist.

## 0.2.0

- **Breaking:** the workflow's `egress-endpoints` is a JSON list
  (`'["llm-proxy.example.com:443"]'`). harden-runner's agent splits its
  allow-list on single spaces, so the entries 0.1.0 took one per line
  arrived as one broken entry and the review job could reach none of them
  (on NotedThat, `cargo fetch` hung). The end-to-end test now lists a real
  host and fetches from it.

## 0.1.0

The Goose review from NotedThat (PR #207, main at 9ea74f7), extracted and
made configurable:

- The composite actions `tidy`, `review`, `post` and `summary`, and the
  pre-composed reusable workflow `.github/workflows/review.yml` that wires
  them (lanes as JSON; its own actions pinned to the release's code).
- Everything the review looks for is the caller's: checks and facts
  directories, a check subset per lane, ignored globs, a tools file, a
  rules file, provider templates.
- Providers routed (`PROVIDER_ROUTES`) or direct, with their keys in
  `PROVIDER_ENV`; a preflight of each provider before any model runs; the
  job log masks every derived secret.
- GitHub Enterprise endpoints via GITHUB_API_URL and GITHUB_SERVER_URL.
