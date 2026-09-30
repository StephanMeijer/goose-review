#!/usr/bin/env bash
# Every pin of the reusable workflows' own actions must be a commit in
# HEAD's history whose action code (the actions, the engine and the scripts
# they run) is exactly HEAD's: pinning review.yml therefore pins what it
# runs. Needs the full history (fetch-depth: 0).
set -euo pipefail
cd "$(dirname "$0")/.."
code=(lanes tools review post tidy goose_review.py setup-providers.sh render-provider.sh options.sh)
pins=$(grep -hoE 'StephanMeijer/goose-review/(lanes|tools|review|post|tidy)@[0-9a-f]{40}' \
  .github/workflows/review.yml | sed 's/.*@//' | sort -u)
if [ -z "$pins" ]; then
  echo "::error::the reusable workflows pin none of their actions" >&2
  exit 1
fi
status=0
for pin in $pins; do
  if ! git merge-base --is-ancestor "$pin" HEAD 2>/dev/null; then
    echo "::error::pinned $pin is not in HEAD's history" >&2
    status=1
  elif ! git diff --quiet "$pin" HEAD -- "${code[@]}"; then
    echo "::error::the action code changed since pinned $pin; commit it, then run scripts/pin.sh and commit the pin" >&2
    git diff --stat "$pin" HEAD -- "${code[@]}" >&2
    status=1
  fi
done
[ "$status" -eq 0 ] && echo "pins ok: $pins"
exit "$status"
