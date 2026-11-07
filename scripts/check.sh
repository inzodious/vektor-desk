#!/usr/bin/env bash
# Every local check a PR needs, since the repo uses no GitHub Actions minutes. Run from anywhere:
#   scripts/check.sh            lint, format, tests, shellcheck, compose, secrets scan, and the UI when ui/ exists
#   scripts/check.sh --docker   also builds both images (the Caddy build validates the Caddyfile)
# Prints one line per step and exits non-zero if any failed. Paste the summary into the PR body.
# shellcheck disable=SC2329
set -Euo pipefail
cd "$(dirname "$0")/.." || exit 1

# ---- Settings ----

DOCKER=0
[ "${1:-}" = --docker ] && DOCKER=1
BIN=.venv/bin
[ -x "$BIN/python" ] || BIN=$(dirname "$(command -v python3)")
LOGS=$(mktemp -d)
RESULTS=()
FAILED=0
SECRETS='sk-ant-[a-z0-9]{2,}-|tskey-(auth|client)-[A-Za-z0-9]{6,}|pk1_[0-9a-f]{20,}|sk1_[0-9a-f]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|"private_key_id": *"[0-9a-f]{20,}"|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}'
BANNED='\.(csv|xlsx|ofx|qfx|pdf|db|sqlite)$|(^|/)[^/]*\.env$'

# ---- Helpers ----

step() {
  local name=$1 log
  shift
  log="$LOGS/${name//[^a-z0-9]/-}.log"
  if "$@" >"$log" 2>&1; then
    RESULTS+=("ok    $name")
  else
    RESULTS+=("FAIL  $name (see $log)")
    FAILED=1
    tail -n 30 "$log" | sed 's/^/      /'
  fi
}

skip() { RESULTS+=("skip  $1: $2"); }

tracked() { git ls-files -co --exclude-standard; }

no_secrets() {
  local hits
  hits=$(tracked | grep -v -E '^scripts/check\.sh$' | xargs -r -d '\n' grep -l -I -E "$SECRETS" 2>/dev/null || true)
  [ -z "$hits" ] || {
    echo "possible keys or tokens in: $hits"
    return 1
  }
  hits=$(tracked | grep -E "$BANNED" | grep -v -E '\.env\.example$' || true)
  [ -z "$hits" ] || {
    echo "data or env files that never belong in the repo: $hits"
    return 1
  }
}

ui() {
  cd ui || return 1
  if [ ! -d node_modules ]; then
    if [ -f package-lock.json ]; then npm ci; else npm install; fi
  fi
  npm run lint --if-present && npm test --if-present && npm run build && test -f dist/index.html
}

# ---- Checks ----

step "ruff check" "$BIN/ruff" check .
step "ruff format" "$BIN/ruff" format --check .
step "pytest" "$BIN/python" -m pytest -q
if command -v shellcheck >/dev/null || [ -x "$BIN/shellcheck" ]; then
  step "shellcheck" "$(command -v "$BIN/shellcheck" || command -v shellcheck)" deploy/*.sh scripts/*.sh
else
  skip shellcheck "not installed (uv pip install -e \".[dev]\")"
fi
step "secrets scan" no_secrets
if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then
  step "compose config" docker compose -f deploy/compose.yaml config -q
else
  skip "compose config" "no docker compose"
fi
if [ -f ui/package.json ]; then
  if command -v npm >/dev/null; then step "ui lint, test, build" ui; else skip ui "no npm"; fi
else
  skip ui "no ui/ yet"
fi
if [ "$DOCKER" -eq 1 ]; then
  step "build vektor-desk:local" docker build -q -t vektor-desk:local .
  step "build vektor-desk/caddy:local" docker build -q -t vektor-desk/caddy:local deploy/caddy
else
  skip "image builds" "add --docker"
fi

# ---- Summary ----

echo
printf '%s\n' "${RESULTS[@]}"
exit "$FAILED"
