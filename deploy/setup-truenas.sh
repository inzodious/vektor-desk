#!/usr/bin/env bash
# First-time setup of Vektor Desk on TrueNAS SCALE (docs/setup.md, step 5). Run as root, from anywhere:
#   sudo bash setup-truenas.sh [path to the service account key .json]
#   sudo bash setup-truenas.sh set KEY    change one value (DESK_SEC_USER_AGENT, TIINGO_API_KEY, …), then redeploy
# Safe to run again: it keeps what's already there and only asks for what's missing.
set -Eeuo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
trap 'echo "Stop: line $LINENO failed: $BASH_COMMAND. Nothing after it ran; fix that and run this script again." >&2' ERR

ROOT=${DESK_ROOT:-/mnt/Manifest/apps/vektor-desk}
SRC=${DESK_SRC:-/mnt/Manifest/apps/vektor-desk-src}
DEPLOY=${DESK_DEPLOY:-$SRC/deploy/deploy.sh}
CREDENTIALS=/mnt/Manifest/apps/.git-credentials
PINNED=/mnt/Manifest/apps/.vektor-desk-deploy/deploy.sh
REPO=https://github.com/inzodious/vektor-desk.git

[ "$(id -u)" -eq 0 ] || {
  echo "Run it as root: sudo bash $0" >&2
  exit 1
}

# ---- Values ----

ask() {
  local prompt=$1 secret=${2:-} value
  if [ -n "$secret" ]; then
    read -rsp "$prompt: " value
    echo >&2
    printf '%s' "$value" | tr -d '[:space:]'
  else
    read -rp "$prompt: " value
    printf '%s' "$value"
  fi
}

env_line() {
  local key=$1 value=$2
  if [[ "$value" =~ ^[A-Za-z0-9_./:@+=,-]*$ ]]; then
    printf '%s=%s' "$key" "$value"
  elif [[ "$value" != *"'"* ]]; then
    printf "%s='%s'" "$key" "$value"
  else
    echo "Stop: $key can't contain a single quote." >&2
    return 1
  fi
}

write_env() {
  local file=$1
  shift
  umask 077
  printf '%s\n' "$@" >"$file.new"
  chmod 600 "$file.new"
  mv "$file.new" "$file"
}

keep() {
  local file=$1 answer
  [ -s "$file" ] || return 1
  read -rp "$(basename "$file") exists. Keep it? [Y/n] " answer
  [ "${answer,,}" != n ]
}

env_file_for() {
  local key=$1 f
  case $key in
    DESK_FIREBASE_PROJECT | DESK_UID | DESK_CLAUDE_TOKEN_EXPIRES) echo settings.env ;;
    CLAUDE_CODE_OAUTH_TOKEN | TIINGO_API_KEY | FINNHUB_API_KEY | FRED_API_KEY | DESK_SEC_USER_AGENT | ALPACA_API_KEY_ID | ALPACA_API_SECRET_KEY) echo desk.env ;;
    PORKBUN_API_KEY | PORKBUN_API_SECRET_KEY) echo caddy.env ;;
    TS_AUTHKEY) echo tailscale.env ;;
    *)
      for f in settings.env desk.env caddy.env tailscale.env; do
        if grep -qE "^(export[[:space:]]+)?$key=" "$ROOT/$f" 2>/dev/null; then
          echo "$f"
          return 0
        fi
      done
      if is_secret "$key"; then echo desk.env; else echo settings.env; fi
      ;;
  esac
}

is_secret() {
  case $1 in
    DESK_CLAUDE_TOKEN_EXPIRES | DESK_SEC_USER_AGENT | DESK_FIREBASE_PROJECT | DESK_UID) return 1 ;;
    *TOKEN* | *KEY* | *SECRET* | *PASSWORD*) return 0 ;;
    *) return 1 ;;
  esac
}

set_key() {
  local key=$1 file value line
  [[ "$key" =~ ^[A-Z_][A-Z0-9_]*$ ]] || {
    echo "usage: setup-truenas.sh set KEY   (e.g. DESK_SEC_USER_AGENT, TIINGO_API_KEY, DESK_MARGIN_RATE_PCT)" >&2
    exit 2
  }
  file=$ROOT/$(env_file_for "$key")
  if is_secret "$key"; then
    value=$(ask "$key (nothing is shown)" secret)
  else
    value=$(ask "$key")
  fi
  line=$(env_line "$key" "$value") || exit 1
  touch "$file"
  chmod 600 "$file"
  umask 077
  awk -v key="$key" -v line="$line" '
    $0 ~ "^(export[[:space:]]+)?" key "=" { if (!done) print line; done = 1; next }
    { print }
    END { if (!done) print line }' "$file" >"$file.new"
  chmod 600 "$file.new"
  mv "$file.new" "$file"
  unset value line
  echo "Saved $key in $(basename "$file")"
  echo "Redeploying so the containers pick it up (a restart doesn't re-read env files)"
  bash "$DEPLOY" redeploy
}

if [ "${1:-}" = set ]; then
  set_key "${2:-}"
  exit 0
fi

# ---- 1. Datasets and folders ----

dataset() {
  local d=$1
  zfs list -H "$d" >/dev/null 2>&1 && return 0
  if [ -n "$(ls -A "/mnt/$d" 2>/dev/null)" ]; then
    echo "   /mnt/$d already has files; keeping it as a folder"
    return 0
  fi
  if zfs list -H "$(dirname "$d")" >/dev/null 2>&1; then
    midclt call pool.dataset.create "{\"name\": \"$d\"}" >/dev/null 2>&1 || sleep 20
    zfs list -H "$d" >/dev/null 2>&1 && return 0
  fi
  echo "   /mnt/$d as a plain folder (no dataset could be made there)"
  mkdir -p "/mnt/$d"
}

for d in Manifest/apps/vektor-desk Manifest/apps/vektor-desk-src Singularity/backups/vektor-desk; do
  dataset "$d"
done
mkdir -p "$ROOT"/data/{home,inbox/fidelity,run/logs,lab/data,lab/queue,lab/runs} "$ROOT"/caddy/{data,config} "$ROOT"/tailscale "$ROOT"/ntfy "$ROOT"/eval/{home,work}
chown -R 568:568 "$ROOT/data" "$ROOT/ntfy" "$ROOT/eval"
chmod 700 "$ROOT/eval/home"
chmod 700 "$ROOT/tailscale" "$ROOT/caddy"
echo "1. Datasets and folders ready under $ROOT"

# ---- 2. Checkout ----

if [ ! -d "$SRC/.git" ]; then
  [ -f "$CREDENTIALS" ] || {
    echo "Stop: $CREDENTIALS is missing (the GitHub token the other apps clone with)." >&2
    exit 1
  }
  git -c credential.helper="store --file=$CREDENTIALS" clone --quiet "$REPO" "$SRC"
fi
echo "2. Checkout at $SRC ($(git -C "$SRC" -c safe.directory="$SRC" log -1 --format='%h %s'))"

# ---- 3. Settings and secrets ----

if ! keep "$ROOT/settings.env"; then
  project=$(ask "Firebase project ID (Escape Vektor's FIREBASE_PROJECT_ID)")
  uid=$(ask "Your Escape Vektor user ID (Firebase Authentication → Users → User UID)")
  expires=$(ask "Claude token expiry, YYYY-MM-DD [$(date -d '+1 year' +%F)]")
  write_env "$ROOT/settings.env" "$(env_line DESK_FIREBASE_PROJECT "$project")" "$(env_line DESK_UID "$uid")" "$(env_line DESK_CLAUDE_TOKEN_EXPIRES "${expires:-$(date -d '+1 year' +%F)}")"
fi
if ! keep "$ROOT/desk.env"; then
  echo "Paste each value; nothing is shown. Leave a market key blank to add it later."
  claude=$(ask "Claude token (claude setup-token on your PC)" secret)
  tiingo=$(ask "Tiingo key" secret)
  finnhub=$(ask "Finnhub key" secret)
  fred=$(ask "FRED key (free, fred.stlouisfed.org)" secret)
  sec=$(ask "SEC contact for its User-Agent, e.g. 'Vektor Desk you@example.com'")
  alpaca_id=$(ask "Alpaca PAPER key ID (Paper Trading dashboard; never live keys)" secret)
  alpaca_secret=$(ask "Alpaca PAPER secret key" secret)
  write_env "$ROOT/desk.env" "CLAUDE_CODE_OAUTH_TOKEN=$claude" "TIINGO_API_KEY=$tiingo" "FINNHUB_API_KEY=$finnhub" "FRED_API_KEY=$fred" "$(env_line DESK_SEC_USER_AGENT "$sec")" \
    "ALPACA_API_KEY_ID=$alpaca_id" "ALPACA_API_SECRET_KEY=$alpaca_secret"
  unset claude tiingo finnhub fred alpaca_id alpaca_secret
fi
if ! keep "$ROOT/caddy.env"; then
  key=$(ask "Porkbun API key (pk1_…)" secret)
  secret=$(ask "Porkbun secret API key (sk1_…)" secret)
  write_env "$ROOT/caddy.env" "PORKBUN_API_KEY=$key" "PORKBUN_API_SECRET_KEY=$secret"
  unset key secret
fi
if ! keep "$ROOT/tailscale.env"; then
  authkey=$(ask "Tailscale auth key (tskey-auth-…, tag:desk)" secret)
  write_env "$ROOT/tailscale.env" "TS_AUTHKEY=$authkey"
  unset authkey
fi
echo "3. settings.env, desk.env, caddy.env and tailscale.env saved (root only)"

# ---- 4. Firestore read-only key ----

key=${1:-}
if [ -n "$key" ]; then
  python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["type"] == "service_account"' "$key" || {
    echo "Stop: $key isn't a service account key." >&2
    exit 1
  }
  install -m 400 -o 568 -g 568 "$key" "$ROOT/firestore-reader.json"
  shred -u "$key" 2>/dev/null || rm -f "$key"
fi
[ -s "$ROOT/firestore-reader.json" ] || {
  echo "Stop: no $ROOT/firestore-reader.json yet. Copy the key to the NAS and run: sudo bash $0 /path/to/key.json" >&2
  exit 1
}
echo "4. Firestore key in place (owned by apps, read-only)"

# ---- 5. Cron copy of deploy.sh, then the images ----

install -D -m 700 "$SRC/deploy/deploy.sh" "$PINNED"
echo "5. Building the images (a few minutes)"
bash "$SRC/deploy/deploy.sh" now
echo
echo "Next: Apps → Discover Apps → ⋮ → Install via YAML, name it vektor-desk, paste $SRC/deploy/compose.yaml (docs/setup.md, step 6)."
