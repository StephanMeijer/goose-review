#!/usr/bin/env bash
# Prepare a job where Goose runs (the review and verify actions): the
# environment Goose gets, Goose itself and the tools the tools prompt
# names, all from release archives pinned by sha256 -- not apt, whose
# mirrors an egress policy would have to allow. git and jq come with the
# runner.
#
# Environment: LOG_DIR (where the transcripts go), INSTALL_GOOSE and
# INSTALL_TOOLS (`true` or not), GOOSE_VERSION, GOOSE_SHA256.
set -euo pipefail

bin="$RUNNER_TEMP/bin"
mkdir -p "$bin"
echo "$bin" >>"$GITHUB_PATH"
{
  # Config (with the providers) and transcripts live outside the checkout
  # the agent works in.
  echo "XDG_CONFIG_HOME=$RUNNER_TEMP/goose-config"
  echo "GOOSE_REVIEW_LOG_DIR=$LOG_DIR"
  # No keyring on a runner; keys come from provider-env.
  echo "GOOSE_DISABLE_KEYRING=1"
  # Goose reports usage unless told not to.
  echo "GOOSE_TELEMETRY_OFF=1"
  echo "GOOSE_TELEMETRY_ENABLED=false"
} >>"$GITHUB_ENV"

cd "$RUNNER_TEMP"
fetch() { curl -sSfL -o "$1" "$2" && echo "$3  $1" | sha256sum -c -; }

if [ "${INSTALL_GOOSE:-true}" = true ]; then
  fetch goose.tar.gz \
    "https://github.com/block/goose/releases/download/$GOOSE_VERSION/goose-x86_64-unknown-linux-gnu.tar.gz" "$GOOSE_SHA256"
  tar xzf goose.tar.gz -C "$bin" ./goose
  "$bin/goose" --version
fi

if [ "${INSTALL_TOOLS:-true}" = true ]; then
  rg_version=15.2.0
  fd_version=v10.5.0
  ast_grep_version=0.45.3
  rg="ripgrep-$rg_version-x86_64-unknown-linux-musl"
  fetch rg.tar.gz "https://github.com/BurntSushi/ripgrep/releases/download/$rg_version/$rg.tar.gz" \
    33e15bcf1624b25cdd2a55813a47a2f95dbe126268203e76aa6a585d1e7b149c
  tar xzf rg.tar.gz -C "$bin" --strip-components=1 "$rg/rg"
  fd="fd-$fd_version-x86_64-unknown-linux-musl"
  fetch fd.tar.gz "https://github.com/sharkdp/fd/releases/download/$fd_version/$fd.tar.gz" \
    761c72dc8e120d85b22292063be8a796e2eeb20eb3e4f38b8fa2343ccf3514a7
  tar xzf fd.tar.gz -C "$bin" --strip-components=1 "$fd/fd"
  fetch ast-grep.zip "https://github.com/ast-grep/ast-grep/releases/download/$ast_grep_version/app-x86_64-unknown-linux-gnu.zip" \
    f8ac830881339d1edee6b2652f54798c0f4da5a827f2db38a08ee31117783ce8
  unzip -q -o ast-grep.zip ast-grep -d "$bin"
  "$bin/rg" --version | head -1
  "$bin/fd" --version
  "$bin/ast-grep" --version
fi
