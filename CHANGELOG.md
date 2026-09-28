# Changelog

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
