---
name: github-actions
description: GitHub Actions behaviour review models got wrong here.
paths: [".github/**"]
---

Each of these was the premise of a finding that turned out false. Trust
them over what you remember.

- **Status check functions in `if:`.** A job or step whose `if:` contains
  none of `success()`, `failure()`, `always()` or `cancelled()` gets an
  implicit `success() &&`.
