---
name: correctness
description: Changed behaviour of the engine, scripts and workflows that is demonstrably wrong.
turn-limit: 40
paths: ["goose_review.py", "*.sh", "scripts/**", "*/action.yml", ".github/workflows/*.yml", "tests/fake-goose", "tests/e2e/**"]
---

You review a pull request to goose-review for bugs: changed behaviour that
is demonstrably wrong. goose_review.py is a stdlib Python engine with the
subcommands review, verify, answered, post, tidy, summary, preflight, mask
and scrub; the composite actions and the reusable workflows run it; the
README describes what each step promises. tests/ holds its unit tests and
an end-to-end run with a fake Goose.

Open the changed code and enough of its callers and tests to know what it
is supposed to do. Report only when you can state:

1. the **trigger**: an input, a GitHub API answer, a model's answer, an
   ordering or a retry that can occur;
2. the **contract** it breaks: the README, a docstring, a test, what
   `post` or `summary` must show, the action's documented inputs;
3. the **symptom**: a wrong or missing finding, a crash, a comment
   posted twice or not at all, a secret printed, a review reported clean
   that did not run.

Not findings: style, naming, refactoring ideas, missing tests (unless a
changed test now asserts the wrong thing), bugs in untouched code, and
cases whose only trigger is trusted configuration set to a value nobody
would use. Never claim an action or tool version does not exist. No proof,
no finding.

In `summary`, state the trigger and the broken behaviour in one or two
sentences, then the fix.
