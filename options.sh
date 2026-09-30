# shellcheck shell=bash
# Sourced by the review action's review step: turns the caller's settings
# (in the environment, never interpolated into a script) into the
# goose_review.py options every lane's review and verify share. One glob
# per line for IGNORE (blank lines and surrounding whitespace dropped).
#
# Sets `options`.

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
if [ -n "${TOOLS:-}" ]; then options+=(--tools "$TOOLS"); fi
if [ -n "${RULES_FILE:-}" ]; then options+=(--rules-file "$RULES_FILE"); fi

