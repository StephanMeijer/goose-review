#!/usr/bin/env bash
# Release v<version> from main.
#
# 1. Checks: a clean main, level with origin; the tests; the pins
#    (review.yml and lane.yml must carry HEAD's action code).
# 2. Tags HEAD v<version> and moves the major tag (v0 for 0.x.y) to it.
# 3. Points the examples and the README at the release commit, in a commit
#    of its own (a commit cannot name itself), and pushes main and the tags.
#
# Usage: scripts/release.sh <version>    e.g. scripts/release.sh 0.1.0
set -euo pipefail
cd "$(dirname "$0")/.."

version=${1:?usage: scripts/release.sh <version>}
[[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "version must be X.Y.Z" >&2; exit 1; }
tag="v$version"
major="v${version%%.*}"

[ "$(git branch --show-current)" = main ] || { echo "not on main" >&2; exit 1; }
[ -z "$(git status --porcelain)" ] || { echo "the working tree is not clean" >&2; exit 1; }
git fetch -q origin main --tags
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || { echo "main is not level with origin/main" >&2; exit 1; }
if git rev-parse -q --verify "refs/tags/$tag" >/dev/null; then echo "$tag exists" >&2; exit 1; fi

python3 -m unittest discover -s tests -q
scripts/check-pins.sh

sha=$(git rev-parse HEAD)
git tag -a "$tag" -m "goose-review $tag" "$sha"
git tag -f -a "$major" -m "goose-review $major (moves with each $major.x release; points at $tag)" "$sha" >/dev/null

# Every `StephanMeijer/goose-review/...@<sha>` in the examples and the
# README names the release commit and its tag.
sed -i -E "s#(StephanMeijer/goose-review/[A-Za-z0-9_./-]+)@[0-9a-f]{40}( \# v[^ ]+)?#\\1@$sha \# $tag#g" \
  README.md examples/caller.yml examples/hand-wired/*.yml
if ! git diff --quiet; then
  git add README.md examples
  git commit -q -m "docs: point the examples at $tag"
fi

git push -q origin main "refs/tags/$tag"
git push -q -f origin "refs/tags/$major"
echo "released $tag at $sha; $major moved to it"
