#!/usr/bin/env bash
# Install the caller's Goose provider templates into Goose's config.
#
# Every *.json in <providers-dir> is a template. One that has a route in
# $GOOSE_REVIEW_PROVIDER_ROUTES (lines `<template name>=<url>`, the name
# being the file name without .json) is rendered for it by
# render-provider.sh; any other is installed as written (a provider reached
# directly, its key named by `api_key_env`). A template still carrying an
# example.invalid placeholder without a route is an error, as is a route for
# a template that does not exist. Routes are secrets: never printed.
#
# Usage: setup-providers.sh <providers-dir> <custom_providers dir>
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
src=$1
out=$2

shopt -s nullglob
templates=("$src"/*.json)
if [ ${#templates[@]} -eq 0 ]; then
  echo "::error::no provider templates (*.json) in $src" >&2
  exit 1
fi

declare -A routes=()
while IFS= read -r line || [ -n "$line" ]; do
  line=${line%$'\r'}
  [ -z "${line//[[:space:]]/}" ] && continue
  if [[ $line != *=* ]]; then
    echo "::error::provider-routes: a line is not <template name>=<url>" >&2
    exit 1
  fi
  name=$(tr -d '[:space:]' <<<"${line%%=*}")
  if [ ! -f "$src/$name.json" ]; then
    echo "::error::provider-routes names '$name', but $src/$name.json does not exist" >&2
    exit 1
  fi
  routes[$name]=${line#*=}
done <<<"${GOOSE_REVIEW_PROVIDER_ROUTES:-}"

mkdir -p "$out"
for template in "${templates[@]}"; do
  name=$(basename "$template" .json)
  if [ -n "${routes[$name]+set}" ]; then
    "$here/render-provider.sh" "$template" "${routes[$name]}" "$out"
  elif grep -q 'example\.invalid' "$template"; then
    echo "::error::$name has an example.invalid placeholder but no route in provider-routes" >&2
    exit 1
  else
    cp "$template" "$out/$name.json"
  fi
  if [ -n "${routes[$name]+set}" ]; then how="rendered for its route"; else how="installed as written"; fi
  echo "provider $name: $how"
done
