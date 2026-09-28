#!/usr/bin/env bash
# The end-to-end test's `setup`: puts tests/fake-goose on PATH as `goose`,
# serves /v1/models and /r1/models on 127.0.0.1:8765 for the preflight, and
# tells the fake which models answer empty (their lane's backup verifies)
# and which are slow (their lane posts last, into the open thread).
set -euo pipefail
fake="$RUNNER_TEMP/fake"
mkdir -p "$fake/bin" "$fake/www/v1" "$fake/www/r1"
cp tests/fake-goose "$fake/bin/goose"
echo '{"data": []}' > "$fake/www/v1/models"
echo '{"data": []}' > "$fake/www/r1/models"
nohup python3 -m http.server 8765 --bind 127.0.0.1 --directory "$fake/www" >/dev/null 2>&1 &
for _ in $(seq 20); do curl -sf http://127.0.0.1:8765/v1/models >/dev/null && break; sleep 0.5; done
echo "$fake/bin" >> "$GITHUB_PATH"
# A host allowed only through the caller's egress-endpoints: blocked, this
# fails the review job, and with it the end-to-end assertions.
if [ "${E2E_EGRESS_PROBE:-true}" = true ]; then
  curl -sSf --max-time 20 -o /dev/null https://index.crates.io/config.json
fi
{
  echo "FAKE_GOOSE_EMPTY_MODELS=fake-empty"
  echo "FAKE_GOOSE_SLOW_MODELS=fake-b"
  echo "FAKE_GOOSE_SLOW_SECONDS=90"
} >> "$GITHUB_ENV"
