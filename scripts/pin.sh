#!/usr/bin/env bash
# Pin the reusable workflows' own actions to a commit.
#
# `uses:` must be a fixed string, and a commit cannot name itself, so the
# workflows pin the actions to the commit holding their code: commit the
# change to the actions first, then run this and commit the pin on top.
# scripts/check-pins.sh holds every pin to the code at HEAD.
#
# Usage: scripts/pin.sh [commit]   (default HEAD)
set -euo pipefail
cd "$(dirname "$0")/.."
sha=$(git rev-parse --verify "${1:-HEAD}^{commit}")
sed -i -E "s#(uses: StephanMeijer/goose-review/(lanes|review|post|tidy|summary))@[0-9a-f]{40}#\\1@$sha#" \
  .github/workflows/review.yml .github/workflows/lane.yml
grep -c "StephanMeijer/goose-review/.*@$sha" .github/workflows/review.yml .github/workflows/lane.yml
