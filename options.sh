# shellcheck shell=bash
# Sourced by the review action's review and verify steps: turns the
# caller's settings (in the environment, never interpolated into a script)
# into goose_review.py options. One value per line for CHECKS and IGNORE;
# blank lines and surrounding whitespace are dropped.
#
# Sets `options` (shared by review and verify) and `checks` (review only).

lines() {
  local line
  while IFS= read -r line || [ -n "$line" ]; do
    line=${line%$'\r'}
    line=${line#"${line%%[![:space:]]*}"}
    line=${line%"${line##*[![:space:]]}"}
    [ -n "$line" ] && printf '%s\n' "$line"
  done <<<"$1"
}

options=(--checks-dir "${CHECKS_DIR:-.agents/checks}" --facts-dir "${FACTS_DIR:-.agents/facts}")
while IFS= read -r glob; do options+=(--ignore "$glob"); done < <(lines "${IGNORE:-}")
if [ -n "${TOOLS_FILE:-}" ]; then options+=(--tools-file "$TOOLS_FILE"); fi
if [ -n "${RULES_FILE:-}" ]; then options+=(--rules-file "$RULES_FILE"); fi

checks=()
while IFS= read -r name; do checks+=(--check "$name"); done < <(lines "${CHECKS:-}")
