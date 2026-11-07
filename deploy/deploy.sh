#!/usr/bin/env bash
# Vektor Desk on TrueNAS SCALE (docs/architecture.md, docs/setup.md). Run as root:
#   deploy.sh now      pull main, build what changed, back up, restart the app; back to the previous images if it isn't
#                      healthy. Waits for nothing: refuses while a desk job (mirror, engine, agent, lab) is running.
#   deploy.sh auto     what the auto-deploy cron job runs every 5 minutes: deploys when main has moved, quietly does nothing
#                      otherwise, waits out a running job, and doesn't retry a commit that failed
#   deploy.sh status   what's live, what's on GitHub, the desk's own status, the last log lines
#   deploy.sh backup   the nightly backup: consistent copies of every SQLite file plus the inbox, to the Singularity pool
#   deploy.sh restore-test  restore drill: unpacks the newest backup into a scratch folder and checks every database
#                      opens, passes its integrity check and has the expected tables; the live data isn't touched
#   deploy.sh check    end-to-end checks: Claude sign-in, Firestore read access, the DNS records against the tailnet and
#                      home-network addresses, a test phone alert
#   deploy.sh logs     redacted tails of every desk service's log into data/run/logs, for the eval container
#                      (docs/eval-access.md); auto does this every 5 minutes
#   deploy.sh card     the app's icon and Web UI button in TrueNAS Apps; TrueNAS drops them when the YAML is edited, so
#                      now and auto put them back
# Unattended runs (auto, backup) also send a phone alert on the desk-ops topic when they stop on an error.
set -Eeuo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export GIT_TERMINAL_PROMPT=0

# ---- Settings ----

APP=${DESK_APP:-vektor-desk}
ROOT=${DESK_ROOT:-/mnt/Manifest/apps/vektor-desk}
SRC=${DESK_SRC:-/mnt/Manifest/apps/vektor-desk-src}
BACKUPS=${DESK_BACKUPS:-/mnt/Singularity/backups/vektor-desk}
BRANCH=${DESK_BRANCH:-main}
CREDENTIALS=${DESK_GIT_CREDENTIALS:-/mnt/Manifest/apps/.git-credentials}
PINNED=${DESK_PINNED:-/mnt/Manifest/apps/.vektor-desk-deploy/deploy.sh}
APP_CONFIGS=${DESK_APP_CONFIGS:-/mnt/.ix-apps/app_configs}
ICON_URL=${DESK_ICON_URL:-https://desk-lan.escape-vektor.com/icon-512.png}
PORTAL_URL=${DESK_PORTAL_URL:-https://desk-lan.escape-vektor.com/}
KEEP=${DESK_BACKUP_KEEP:-14}
HEALTH_WAIT=${DESK_HEALTH_WAIT:-120}
LOG=$ROOT/deploy.log
BUILD_LOG=$ROOT/deploy-build.log
DEBUG_MAX=${DESK_DEBUG_MAX:-104857600}
LOCK=/run/vektor-desk-deploy.lock
AUTO_FAILED=$ROOT/deploy-auto.failed
AUTO_NOTE=$ROOT/deploy-auto.note
BUSY=75
IMAGES=("vektor-desk:local=." "vektor-desk/caddy:local=deploy/caddy")

# ---- Helpers ----

log() { printf '%s %s\n' "$(date '+%F %T')" "$*" | tee -a "$LOG"; }
alert() {
  [ -n "${ALERTS:-}" ] || return 0
  timeout 20 docker exec vektor-desk-cron python -m desk.notify send ops "$1" "$2" --priority high --tags warning >/dev/null 2>&1 || true
}
die() {
  log "Stopped: $1"
  [ "${2:-1}" = "$BUSY" ] || alert "${ALERTS:-}" "$1"
  exit "${2:-1}"
}

repo() { git -C "$SRC" -c safe.directory="$SRC" -c credential.helper="store --file=$CREDENTIALS" "$@"; }

app_state() { midclt call app.query "[[\"name\", \"=\", \"$APP\"]]" | jq -r '.[0].state // "MISSING"'; }
image_build() { docker image inspect -f '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$1" 2>/dev/null || true; }
live_build() { docker inspect -f '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$1" 2>/dev/null || true; }
health() { docker inspect -f '{{ if .State.Health }}{{ .State.Health.Status }}{{ else }}{{ .State.Status }}{{ end }}' "$1" 2>/dev/null || echo missing; }

run_job() {
  local id state deadline=$((SECONDS + 300))
  id=$(midclt call "$@" 2>>"$BUILD_LOG") || return 1
  [[ "$id" =~ ^[0-9]+$ ]] || return 1
  while [ "$SECONDS" -lt "$deadline" ]; do
    state=$(midclt call core.get_jobs "[[\"id\", \"=\", $id]]" | jq -r '.[0].state // "UNKNOWN"')
    case "$state" in
      SUCCESS) return 0 ;;
      FAILED | ABORTED)
        {
          echo "==== $(date '+%F %T') $1 $id $state"
          midclt call core.get_jobs "[[\"id\", \"=\", $id]]" | jq -r '.[0].error // empty'
        } >>"$BUILD_LOG"
        return 1
        ;;
    esac
    sleep 2
  done
  echo "==== $(date '+%F %T') $1 $id still $state after 300 s" >>"$BUILD_LOG"
  return 1
}

restart_app() {
  run_job app.redeploy "$APP" && return 0
  log "app.redeploy didn't work; stopping and starting $APP instead"
  run_job app.stop "$APP" || true
  run_job app.start "$APP"
}

healthy() {
  local target=$1 deadline=$((SECONDS + HEALTH_WAIT))
  while [ "$SECONDS" -lt "$deadline" ]; do
    if [ "$(live_build vektor-desk-api)" = "$target" ] && [ "$(health vektor-desk-api)" = healthy ] &&
      [ "$(health vektor-desk-cron)" != missing ] && [ "$(health vektor-desk-caddy)" = running ]; then
      return 0
    fi
    sleep 3
  done
  return 1
}

busy() {
  local out rc=0
  out=$(docker exec vektor-desk-cron python -m desk.runlock 2>/dev/null) || rc=$?
  [ "$rc" -eq "$BUSY" ] || return 1
  printf '%s\n' "$out"
}

tarball() {
  local file
  mkdir -p "$BACKUPS"
  file="$BACKUPS/$APP-$(date +%Y%m%d-%H%M%S).tar.gz"
  tar "$@" -czf "$file.part" || {
    rm -f "$file.part"
    return 1
  }
  mv "$file.part" "$file"
  find "$BACKUPS" -maxdepth 1 -name "$APP-*.tar.gz" -printf '%T@ %p\n' | sort -rn | tail -n +$((KEEP + 1)) | cut -d' ' -f2- | xargs -r rm -f
  echo "$file"
}

backup() {
  local staging=$ROOT/data/backup-staging
  [ -d "$ROOT/data" ] || {
    echo "there's no $ROOT/data to back up" >&2
    return 1
  }
  if [ "$(docker inspect -f '{{ .State.Running }}' vektor-desk-cron 2>/dev/null)" = true ]; then
    docker exec vektor-desk-cron python -m desk.backup --out /data/backup-staging >>"$LOG" 2>&1 || return 1
  else
    docker run --rm --user 568:568 -v "$ROOT/data:/data" vektor-desk:local python -m desk.backup --out /data/backup-staging >>"$LOG" 2>&1 || return 1
  fi
  tarball -C "$staging" . || return 1
  rm -rf "$staging"
}

# ---- Commands ----

restore_test() {
  local latest scratch=$ROOT/restore-test rc=0
  latest=$(find "$BACKUPS" -maxdepth 1 -name "$APP-*.tar.gz" -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -n 1 | cut -d' ' -f2-)
  [ -n "$latest" ] || die "there are no backups in $BACKUPS yet; run deploy.sh backup first"
  rm -rf "$scratch"
  mkdir -p "$scratch"
  tar -xzf "$latest" -C "$scratch" || die "couldn't unpack $latest"
  chown -R 568:568 "$scratch"
  echo "Restoring $(basename "$latest") into $scratch"
  docker run --rm --network none --user 568:568 -v "$scratch:/restore" vektor-desk:local python -m desk.backup --verify /restore || rc=$?
  rm -rf "$scratch"
  if [ "$rc" -eq 0 ]; then
    log "Restore drill passed: $(basename "$latest")"
  else
    die "the restore drill failed for $(basename "$latest"); see the problems above"
  fi
}

update_checkout() {
  [ -d "$SRC/.git" ] || die "there's no checkout in $SRC (docs/setup.md, step 5)"
  repo fetch --quiet origin "$BRANCH" 2>>"$LOG" || die "couldn't fetch from GitHub (has the token in $CREDENTIALS expired, or does it lack vektor-desk?)"
  [ -z "$(repo status --porcelain --untracked-files=no)" ] || die "$SRC has local edits; run 'git -C $SRC status' and undo them"
  repo merge --ff-only --quiet "origin/$BRANCH" 2>>"$LOG" || die "$SRC can't fast-forward to origin/$BRANCH"
}

deploy() {
  local state why before target pair image dir built=() previous=() files
  state=$(app_state)
  if [ "$state" = RUNNING ] && why=$(busy); then
    die "a desk job is running: $why. Nothing was changed" "$BUSY"
  fi
  before=$(repo rev-parse HEAD 2>/dev/null || true)
  update_checkout
  target=$(repo rev-parse HEAD)

  for pair in "${IMAGES[@]}"; do
    image=${pair%%=*}
    dir=${pair#*=}
    [ "$(image_build "$image")" = "$target" ] && continue
    log "Building $image ${target:0:7}: $(repo log -1 --format=%s) (output in $BUILD_LOG)"
    echo "==== $(date '+%F %T') build $image ${target:0:7}" >>"$BUILD_LOG"
    docker build --build-arg "DESK_BUILD=$target" --label vektor-desk.app=1 -t "${image%:*}:candidate" "$SRC/$dir" >>"$BUILD_LOG" 2>&1 ||
      die "$image didn't build; the live app wasn't touched. See $BUILD_LOG"
    built+=("$image")
  done

  if [ ${#built[@]} -eq 0 ]; then
    log "Already live: ${target:0:7}"
    rm -f "$AUTO_FAILED"
    return 0
  fi
  for image in "${built[@]}"; do
    if docker image inspect "$image" >/dev/null 2>&1; then
      previous+=("$image")
      docker tag "$image" "${image%:*}:previous"
    fi
    docker tag "${image%:*}:candidate" "$image"
    docker rmi "${image%:*}:candidate" >/dev/null
  done

  if [ "$state" = MISSING ]; then
    log "Built ${built[*]} at ${target:0:7}. There's no app called $APP yet: install it from deploy/compose.yaml (docs/setup.md, step 6)"
    return 0
  fi
  if [ -n "$before" ] && ! repo diff --quiet "$before" "$target" -- deploy/compose.yaml; then
    log "deploy/compose.yaml changed since ${before:0:7}: run setup-truenas.sh, then paste it into Apps → $APP → Edit (docs/setup.md, After updates)"
    alert "Desk needs you" "compose.yaml changed. Run setup-truenas.sh, then paste it into Apps, Edit. See docs/setup.md."
  fi

  files=$(backup) || die "the backup failed, so nothing was restarted"
  log "Backed up: $files"
  log "Restarting $APP"
  if restart_app && healthy "$target"; then
    log "Live: ${target:0:7}"
    rm -f "$AUTO_FAILED"
    docker image prune -f --filter "label=vektor-desk.app=1" >/dev/null 2>&1 || true
    return 0
  fi

  [ ${#previous[@]} -gt 0 ] || die "it didn't come up healthy and there are no previous images. See the app's logs"
  log "It didn't come up healthy; going back to the previous images"
  for image in "${previous[@]}"; do docker tag "${image%:*}:previous" "$image"; done
  if restart_app && [ "$(health vektor-desk-api)" != missing ]; then
    die "rolled back; the previous version is live again. Pre-deploy backup: $files"
  fi
  die "the rollback didn't come up either. Check the app in the TrueNAS Apps screen. Pre-deploy backup: $files"
}

note() {
  [ "$(cat "$AUTO_NOTE" 2>/dev/null)" != "$1" ] || return 1
  printf '%s\n' "$1" >"$AUTO_NOTE"
  log "$1"
}

auto_stopped() {
  if [ "$1" -eq 0 ] || [ "$1" -eq "$BUSY" ]; then return 0; fi
  printf '%s\n' "$AUTO_TARGET" >"$AUTO_FAILED"
}

pinned_stale() { [ -f "$PINNED" ] && ! cmp -s "$PINNED" "$SRC/deploy/deploy.sh"; }

auto() {
  local target why
  exec 9>"$LOCK"
  flock -n 9 || return 0
  [ "$(app_state)" = RUNNING ] || return 0
  if ! repo fetch --quiet origin "$BRANCH" 2>/dev/null; then
    note "Auto-deploy couldn't fetch from GitHub; it keeps trying (has the token in $CREDENTIALS expired?)" || true
    return 0
  fi
  target=$(repo rev-parse "origin/$BRANCH")
  if [ "$(live_build vektor-desk-api)" = "$target" ]; then
    rm -f "$AUTO_NOTE"
    return 0
  fi
  [ "$(cat "$AUTO_FAILED" 2>/dev/null)" != "$target" ] || return 0
  if why=$(busy); then
    note "Auto-deploy is waiting for ${target:0:7}: $why" || true
    return 0
  fi
  rm -f "$AUTO_NOTE"
  log "Auto-deploy: main moved to ${target:0:7}"
  AUTO_TARGET=$target
  ALERTS="Auto-deploy stopped"
  trap 'auto_stopped $?' EXIT
  deploy
  trap - EXIT
  if pinned_stale && note "deploy.sh changed on main; read it, then copy it again for the cron jobs (docs/setup.md, After updates)"; then
    alert "Desk needs you" "deploy.sh changed. Read it, then copy it again for the cron jobs. See docs/setup.md."
  fi
}

status() {
  local why crons
  echo "App:         $APP $(app_state)$(why=$(busy) && echo " (running: $why)")"
  repo fetch --quiet origin "$BRANCH" 2>/dev/null || echo "(couldn't reach GitHub)"
  printf 'Live:        %s\n' "$(live_build vektor-desk-api | cut -c1-7)"
  printf 'On GitHub:   %s\n' "$(repo log -1 --format='%h %s' "origin/$BRANCH")"
  printf 'Containers:  api %s, cron %s, caddy %s, tailscale %s, ntfy %s, lab %s\n' "$(health vektor-desk-api)" "$(health vektor-desk-cron)" "$(health vektor-desk-caddy)" "$(health vektor-desk-tailscale)" "$(health vektor-desk-ntfy)" "$(health vektor-desk-lab)"
  printf 'Tailnet IP:  %s\n' "$(docker exec vektor-desk-tailscale tailscale ip -4 2>/dev/null || echo '?')"
  echo "Backups:     $(find "$BACKUPS" -maxdepth 1 -name "$APP-*.tar.gz" 2>/dev/null | wc -l) in $BACKUPS"
  crons=$(midclt call cronjob.query 2>/dev/null | jq -r '[.[] | select(.enabled and (.command | test("vektor-desk-deploy/deploy\\.sh auto")))] | length' 2>/dev/null || true)
  if [ "${crons:-0}" -gt 0 ]; then echo "Auto-deploy: on"; else echo "Auto-deploy: off (docs/setup.md, step 8)"; fi
  if [ -s "$AUTO_FAILED" ]; then echo "             holding back $(cut -c1-7 "$AUTO_FAILED") after it failed; the next push retries, or run deploy.sh now"; fi
  if [ ! -f "$PINNED" ]; then echo "Cron copy:   none at $PINNED (step 8)"; elif pinned_stale; then echo "Cron copy:   differs from the checkout's deploy.sh; read the change, then copy it again (docs/setup.md, After updates)"; fi
  echo
  docker exec vektor-desk-api python -m desk.status 2>/dev/null || echo "(the desk's own status isn't answering)"
  echo
  tail -n 8 "$LOG" 2>/dev/null || true
}

check() {
  local ip dns lan answer tables
  echo "Claude:"
  answer=$(docker exec vektor-desk-cron sh -c 'cd "$(mktemp -d)" && echo "Reply with the single word OK." | claude -p --model haiku --output-format json --tools "" --setting-sources "" --strict-mcp-config --no-session-persistence' 2>&1 || true)
  if jq -e '.is_error == false' >/dev/null 2>&1 <<<"$answer"; then
    echo "  signed in, answered: $(jq -r '.result' <<<"$answer" | head -c 80)"
  else
    echo "  failed: $(head -c 300 <<<"$answer")"
  fi
  echo "Firestore:"
  if tables=$(docker exec vektor-desk-cron python -m desk.mirror --list 2>&1); then
    echo "  read access ok, $(wc -l <<<"$tables") tables: $(tr '\n' ' ' <<<"$tables")"
  else
    echo "  failed: $(tail -n 1 <<<"$tables")"
  fi
  echo "Address:"
  ip=$(docker exec vektor-desk-tailscale tailscale ip -4 2>/dev/null || true)
  dns=$(getent ahostsv4 desk.escape-vektor.com 2>/dev/null | awk 'NR == 1 { print $1 }')
  echo "  tailnet ${ip:-?}, desk.escape-vektor.com resolves to ${dns:-nothing}"
  if [ -n "$ip" ] && [ "$ip" = "$dns" ]; then echo "  match"; else echo "  set the Porkbun A record for desk to ${ip:-the tailnet address} (step 7)"; fi
  echo "Home network:"
  lan=$(docker port vektor-desk-tailscale 443/tcp 2>/dev/null | head -n 1 | cut -d: -f1)
  dns=$(getent ahostsv4 desk-lan.escape-vektor.com 2>/dev/null | awk 'NR == 1 { print $1 }')
  if [ -z "$lan" ]; then
    echo "  not published: paste the current compose.yaml into the app (docs/setup.md, Home network)"
  else
    echo "  published on $lan, desk-lan.escape-vektor.com resolves to ${dns:-nothing}"
    if [ "$lan" = "$dns" ]; then echo "  match"; else echo "  set the Porkbun A record for desk-lan to $lan (docs/setup.md, Home network)"; fi
  fi
  echo "Phone alerts:"
  docker exec vektor-desk-cron python -m desk.notify test ops 2>&1 | sed 's/^/  /' || true
  echo "  subscribe in the ntfy app: server https://desk.escape-vektor.com:8443, topics desk-alerts, desk-research, desk-ops"
  echo "Certificate:"
  docker logs vektor-desk-caddy 2>&1 | grep -E 'certificate obtained|could not get certificate|obtain' | tail -n 2 | sed 's/^/  /' || true
}

# ---- App card: icon and Web UI button in TrueNAS Apps ----

app_card() {
  local file=$APP_CONFIGS/$APP/metadata.yaml changed
  [ -f "$file" ] || return 0
  changed=$(python3 - "$file" "$APP_CONFIGS/../metadata.yaml" "$APP" "$ICON_URL" "$PORTAL_URL" <<'PY'
import os
import sys

import yaml

path, collective, app, icon, portal = sys.argv[1:6]


def load(p):
    try:
        with open(p) as f:
            return yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        return {}


def card_set(entry):
    return entry.get("metadata", {}).get("icon") == icon and entry.get("portals") == {"Web UI": portal}


data = load(path)
if not card_set(data):
    data.setdefault("metadata", {})["icon"] = icon
    data["portals"] = {"Web UI": portal}
    tmp = path + ".vektor-desk"
    with open(tmp, "w") as f:
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)
    os.chmod(tmp, os.stat(path).st_mode)
    os.replace(tmp, path)
if not card_set(load(collective).get(app, {})):
    print("stale")
PY
  ) || return 1
  [ "$changed" = stale ] || return 0
  if timeout 60 midclt call app.metadata.generate >/dev/null 2>&1; then
    echo "App card: icon and Web UI button set; refresh the Apps page"
  else
    echo "App card: set for $APP, but TrueNAS didn't rebuild its app list; run: midclt call app.metadata.generate" >&2
    return 1
  fi
}

# ---- Logs for the eval container ----

secret_values() {
  local f
  for f in "$ROOT"/*.env; do
    [ -f "$f" ] || continue
    sed -n 's/^[[:space:]]*\(export[[:space:]]\+\)\?[A-Za-z_][A-Za-z0-9_]*=//p' "$f" | sed "s/^[\"']//; s/[\"']\$//"
  done
}

redact() {
  awk -v list="$1" '
    BEGIN { while ((getline line < list) > 0) if (length(line) >= 8 && !index("[redacted]", line)) s[++n] = line }
    {
      for (i = 1; i <= n; i++)
        while ((p = index($0, s[i])) > 0) $0 = substr($0, 1, p - 1) "[redacted]" substr($0, p + length(s[i]))
      print
    }' | sed -E \
    -e 's/(sk-ant-|tskey-|pk1_|sk1_)[A-Za-z0-9_-]+/\1[redacted]/g' \
    -e 's/(Bearer )[A-Za-z0-9._~+\/=-]+/\1[redacted]/g' \
    -e 's/((token|apikey|api_key|key|secret|password)=)[^&[:space:]"]+/\1[redacted]/gI' \
    -e 's/("private_key(_id)?": *")[^"]*/\1[redacted]/g' \
    -e 's/eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/[redacted]/g'
}

logs_export() {
  local out=$ROOT/data/run/logs list name tmp debug
  [ -d "$ROOT/data" ] || return 0
  mkdir -p "$out"
  list=$(mktemp)
  chmod 600 "$list"
  secret_values >"$list"
  for name in api cron caddy ntfy lab tailscale eval; do
    tmp="$out/.$name.log.part"
    docker logs --tail 400 --timestamps "vektor-desk-$name" 2>&1 | redact "$list" >"$tmp" || true
    mv "$tmp" "$out/$name.log"
  done
  {
    tail -n 200 "$LOG" 2>/dev/null || true
    echo "==== build log"
    tail -n 100 "$BUILD_LOG" 2>/dev/null || true
  } | redact "$list" >"$out/.deploy.log.part"
  mv "$out/.deploy.log.part" "$out/deploy.log"
  debug=$ROOT/eval/home/logs/remote-control.log
  tail -n 1000 "$debug" 2>/dev/null | redact "$list" >"$out/.eval-debug.log.part" || true
  mv "$out/.eval-debug.log.part" "$out/eval-debug.log"
  if [ -f "$debug" ] && [ "$(stat -c %s "$debug")" -gt "$DEBUG_MAX" ]; then truncate -s 0 "$debug"; fi
  docker ps -a --filter name=vektor-desk --format '{{.Names}}\t{{.Status}}\t{{.Image}}' >"$out/containers.txt" 2>&1 || true
  date -Is >"$out/exported_at"
  rm -f "$list"
  chown -R 568:568 "$out"
  chmod 640 "$out"/*.log "$out/containers.txt" "$out/exported_at"
}

main() {
  local files
  [ "$(id -u)" -eq 0 ] || {
    echo "Run it as root: sudo bash $0 ${1:-now}" >&2
    exit 1
  }
  mkdir -p "$ROOT"
  case "${1:-now}" in
    now)
      exec 9>"$LOCK"
      flock -n 9 || die "a deploy is already running: tail -f $LOG"
      deploy
      app_card || true
      if pinned_stale; then log "deploy.sh changed: copy it again for the cron jobs (docs/setup.md, After updates)"; fi
      ;;
    backup)
      ALERTS="Nightly backup failed"
      files=$(backup) || die "the backup failed"
      log "Backed up: $files"
      ;;
    auto)
      auto
      app_card >/dev/null 2>&1 || true
      logs_export || true
      ;;
    card) app_card ;;
    logs) logs_export ;;
    status) status ;;
    restore-test) restore_test ;;
    check) check ;;
    *)
      echo "usage: deploy.sh [now | auto | status | backup | restore-test | check | logs | card]" >&2
      exit 2
      ;;
  esac
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then main "$@"; fi
