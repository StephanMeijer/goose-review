# Changelog

## 0.5.0 (unreleased)

- **Breaking:** a run is three jobs, whatever the number of lanes: `plan`
  (check the lanes, collapse resolved threads, mark the run running),
  `review` (every lane at once, in one job) and `post` (one review with
  every lane's findings, then the summary comment). The lane matrix,
  `lane.yml` and the separate `tidy` and `summary` jobs are gone.
- **Breaking (hand-wired callers):** the `review` and `post` actions take
  `lanes` (the same YAML or JSON as the workflow, or the `lanes` action's
  output) instead of one lane's inputs, and `post` writes the summary: the
  `summary` action is gone. `tidy` runs in the plan job.
  See [`examples/hand-wired/`](examples/hand-wired/).
- One review per run instead of one per lane: each comment is still signed
  with its lane's models, and findings of several lanes on the same lines
  share one thread (the most severe opens it, the others reply).
- A lane whose provider does not answer stops alone; the other lanes carry
  on in the same job.
- The review's artifact is one, `goose-review`, with a directory per lane.

## 0.4.0

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
