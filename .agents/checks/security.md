---
name: security
description: Exploitable security holes in the review's workflows, actions and engine.
turn-limit: 40
paths: [".github/workflows/*.yml", "*/action.yml", "goose_review.py", "*.sh", "scripts/**"]
---

A specialist pass beside the broad `general` check: look only for security
holes an attacker can exploit. The README's "Security model" states the
guarantees: a read-only token and blocked egress in the review job, no
GitHub token or raw provider settings for the model, and every output
scrubbed of provider secrets, again in `post`.

Report only a path from an input an attacker controls (the pull request's
text, branch name, files or diff, or what a prompt-injected model writes)
past a missing guard to a crossed boundary (a provider secret or write
token leaving, the caller's repository written), with its impact. If a
guard on the real path stops it, there is no finding. Trusted configuration
set wrongly, hardening ideas and the residual risks the README names are
not findings.

In `summary`, state the exploitable path and its impact, then the fix.
