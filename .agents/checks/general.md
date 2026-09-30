---
name: general
description: The broad review of every changed file -- anything demonstrably wrong in what changed.
turn-limit: 40
paths: []
---

Review this goose-review pull request: every changed file. The README says
what the review promises; the docstrings say what each step does.

Start from the diff and cover all of it before going deep anywhere. Then
investigate only concrete suspicions: read, in one go, the callers, guards,
tests, contracts or base version that decide a claim, and stop once it is
settled. An empty findings list is a valid answer; the time you have is a
ceiling, not a target.

Report what is demonstrably wrong in the changed lines: a bug, a statement
of fact that is false, or a contradiction the change introduces (say what
each side says). Each finding names what triggers it, what it breaks, and
the line that shows it. Not findings: style, naming, refactoring ideas,
missing tests, unchanged code, and what CI's tests, shellcheck and
actionlint already enforce.

In `summary`, state what is wrong and why, then the fix.
