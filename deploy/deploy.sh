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
#                      home-network addresses, the Alpaca paper account (read-only), a test phone alert
#   deploy.sh logs     redacted tails of every desk service's log into data/run/logs, for the eval container
#                      (docs/eval-access.md); auto does this every 5 minutes
#   deploy.sh redeploy recreate the containers on the images already live, so an edited *.env file takes effect (a
#                      docker restart doesn't re-read env files); refuses while a desk job is running
#   deploy.sh box      run the box actions the app asked for (Settings → Box): redeploy, status, check, backup,
#                      restore-test, logs; auto does this every 5 minutes
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
NO_SELF_PIN=${DESK_NO_SELF_PIN:-$ROOT/deploy.no-self-pin}
SELF=${DESK_SELF:-$(readlink -f "${BASH_SOURCE[0]}")}
BOX_ACTIONS="redeploy status check backup restore-test logs update-script apply-compose"
BOX_TIMEOUT=${DESK_BOX_TIMEOUT:-1800}
KEYS_PEM=${DESK_KEYS_PEM:-$ROOT/box-keys.pem}
ENV_FILES="settings.env desk.env caddy.env tailscale.env"
PAPER_URL=https://paper-api.alpaca.markets
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
    log "deploy/compose.yaml changed since ${before:0:7}: Settings → Box → Apply compose (docs/setup.md, After updates)"
    alert "Desk needs you" "compose.yaml changed. Open Settings, Box to apply it."
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

redeploy() {
  local why target
  if why=$(busy); then die "a desk job is running: $why. Nothing was changed" "$BUSY"; fi
  target=$(live_build vektor-desk-api)
  log "Redeploying $APP on ${target:0:7} to pick up the env files"
  if restart_app && healthy "$target"; then
    log "Live again: ${target:0:7}"
    app_card || true
    return 0
  fi
  die "$APP didn't come back healthy after the redeploy. See the app's logs"
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
}

script_from() {
  local want c
  want=$(repo hash-object "$PINNED" 2>/dev/null) || return 1
  for c in $(repo log --format=%H -n 300 HEAD -- deploy/deploy.sh 2>/dev/null); do
    if [ "$(repo rev-parse "$c:deploy/deploy.sh" 2>/dev/null)" = "$want" ]; then
      printf '%s\n' "$c"
      return 0
    fi
  done
  return 1
}

script_state() {
  local head from='' behind=null current=false off=false
  [ ! -e "$NO_SELF_PIN" ] || off=true
  head=$(repo rev-parse HEAD 2>/dev/null) || head=
  if [ ! -f "$PINNED" ]; then
    jq -n --arg at "$(date -u +%FT%TZ)" --argjson off "$off" '{checked_at: $at, pinned: false, current: false, behind: null, from: null, to: null, off: $off}'
    return 0
  fi
  if ! pinned_stale; then
    behind=0
    current=true
    from=$head
  elif from=$(script_from); then
    behind=$(repo rev-list --count "$from..HEAD" -- deploy/deploy.sh 2>/dev/null || echo null)
  else
    from=
  fi
  jq -n --arg at "$(date -u +%FT%TZ)" --arg f "$from" --arg h "$head" --argjson b "$behind" --argjson c "$current" --argjson off "$off" \
    '{checked_at: $at, pinned: true, current: $c, behind: $b, from: (if $f == "" then null else $f end), to: (if $h == "" then null else $h end), off: $off}'
}

script_line() {
  local state behind from to
  state=$(script_state)
  if [ "$(jq -r .pinned <<<"$state")" != true ]; then
    echo "none at $PINNED (docs/setup.md, step 8)"
    return 0
  fi
  [ "$(jq -r .current <<<"$state")" != true ] || {
    echo "current"
    return 0
  }
  behind=$(jq -r '.behind // "some"' <<<"$state")
  from=$(jq -r '.from // "an unknown version" | .[0:7]' <<<"$state")
  to=$(jq -r '.to // "?" | .[0:7]' <<<"$state")
  if [ "$(jq -r .off <<<"$state")" = true ]; then
    echo "$behind commits behind main ($from, main is $to); updating from the app is off ($NO_SELF_PIN), so copy it by hand (docs/setup.md, After updates)"
  else
    echo "$behind commits behind main ($from, main is $to); Settings → Box → Update box script"
  fi
}

update_script() {
  local head from new rc ALERTS=update-script
  [ -f "$PINNED" ] || {
    echo "There's no cron copy at $PINNED yet; set one up first (docs/setup.md, step 8)"
    return 1
  }
  if [ "$(readlink -f "$PINNED")" = "$(readlink -f "$SRC/deploy/deploy.sh")" ]; then
    echo "The cron jobs run the checkout's deploy.sh directly; nothing to copy"
    return 0
  fi
  head=$(repo rev-parse HEAD 2>/dev/null) || {
    echo "Can't read the checkout at $SRC"
    return 1
  }
  if ! pinned_stale; then
    echo "Box script is current at ${head:0:7}"
    return 0
  fi
  if [ -e "$NO_SELF_PIN" ]; then
    echo "Updating from the app is off ($NO_SELF_PIN). Read the change, then copy it by hand (docs/setup.md, After updates)"
    return 1
  fi
  at_main || {
    rc=$?
    return "$rc"
  }
  if ! bash -n "$SRC/deploy/deploy.sh" 2>&1; then
    echo "deploy.sh at ${head:0:7} doesn't parse; the box script stays as it is"
    return 1
  fi
  from=$(script_from) || from=
  new=$(mktemp "$(dirname "$PINNED")/.deploy.sh.XXXXXX")
  cat "$SRC/deploy/deploy.sh" >"$new"
  chmod 700 "$new"
  mv -f "$new" "$PINNED"
  if [ -n "$from" ]; then
    log "Box script updated from ${from:0:7} to ${head:0:7}"
    echo "Changes to deploy.sh:"
    repo log --format='  %h %s' "$from..$head" -- deploy/deploy.sh
  else
    log "Box script updated from an unknown version to ${head:0:7}"
  fi
  alert "Desk updated its box script" "deploy.sh for the cron jobs now matches main at ${head:0:7}."
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
  echo "Box script:  $(script_line)"
  compose_drift
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
  echo "Alpaca paper:"
  docker exec vektor-desk-cron python -m desk.paper_check 2>&1 | sed 's/^/  /' || true
  echo "Phone alerts:"
  docker exec vektor-desk-cron python -m desk.notify test ops 2>&1 | sed 's/^/  /' || true
  echo "  subscribe in the ntfy app: server https://desk.escape-vektor.com:8443, topics desk-alerts, desk-research, desk-ops"
  echo "Box script:"
  echo "  $(script_line)"
  echo "Certificate:"
  docker logs vektor-desk-caddy 2>&1 | grep -E 'certificate obtained|could not get certificate|obtain' | tail -n 2 | sed 's/^/  /' || true
}

# ---- Box actions from the app ----

box_dir() {
  local base want
  base="$(realpath -m "$ROOT")/data/run"
  [ -d "$base" ] && [ ! -L "$base" ] && [ "$(realpath "$base")" = "$base" ] || return 1
  want=$base/box
  if [ -L "$want" ] || [ -L "$want/requests" ]; then return 1; fi
  [ -d "$want" ] || mkdir "$want"
  [ -d "$want/requests" ] || mkdir "$want/requests"
  [ "$(realpath "$want")" = "$want" ] && [ "$(realpath "$want/requests")" = "$want/requests" ] || return 1
  chown 568:568 "$want" "$want/requests" 2>/dev/null || true
  printf '%s\n' "$want"
}

box_put() {
  local dir=$1 name=$2 tmp
  tmp=$(mktemp "$dir/.$name.XXXXXX")
  cat >"$tmp"
  chown 568:568 "$tmp" 2>/dev/null || true
  chmod 644 "$tmp"
  mv -f "$tmp" "$dir/$name"
}

box_run() {
  local dir=$1 action=$2 id=$3 started out rc=0 result list
  started=$(date -u +%FT%TZ)
  jq -n --arg a "$action" --arg id "$id" --arg s "$started" \
    '{action: $a, request_id: (if $id == "" then null else $id end), started: $s, finished: null, result: null, exit_code: null, output: null}' | box_put "$dir" "$action.json"
  log "Box action from the app: $action${id:+ ($id)}"
  out=$(timeout "$BOX_TIMEOUT" bash "$SELF" "$action" 2>&1 </dev/null) || rc=$?
  case $rc in
    0) result=ok ;;
    "$BUSY") result=skipped ;;
    *) result=failed ;;
  esac
  list=$(mktemp)
  chmod 600 "$list"
  secret_values >"$list"
  out=$(printf '%s\n' "$out" | tail -n 300 | redact "$list")
  rm -f "$list"
  jq -n --arg a "$action" --arg id "$id" --arg s "$started" --arg f "$(date -u +%FT%TZ)" --arg r "$result" --argjson rc "$rc" --arg o "$out" \
    '{action: $a, request_id: (if $id == "" then null else $id end), started: $s, finished: $f, result: $r, exit_code: $rc, output: $o}' | box_put "$dir" "$action.json"
}

box_requests() {
  local dir action file id
  dir=$(box_dir) || {
    log "Box actions: $ROOT/data/run/box isn't a plain folder; skipped"
    return 0
  }
  date -u +%FT%TZ | box_put "$dir" host.alive
  script_state 2>/dev/null | box_put "$dir" script.json || true
  compose_state 2>/dev/null | box_put "$dir" compose.json || true
  box_keys "$dir" || true
  for action in $BOX_ACTIONS; do
    file=$dir/requests/$action.json
    if [ -L "$file" ]; then
      rm -f "$file"
      continue
    fi
    [ -f "$file" ] || continue
    id=$(head -c 512 "$file" | jq -r '.id // empty' 2>/dev/null | tr -cd 'a-f0-9' | head -c 32 || true)
    rm -f "$file"
    box_run "$dir" "$action" "$id"
  done
  find "$dir/requests" -maxdepth 1 \( -type f -o -type l \) -name '*.json' -delete 2>/dev/null || true
}

# ---- Keys from the app ----

key_file_for() {
  local key=$1 f
  case $key in
    DESK_FIREBASE_PROJECT | DESK_UID | DESK_CLAUDE_TOKEN_EXPIRES) echo settings.env ;;
    CLAUDE_CODE_OAUTH_TOKEN | TIINGO_API_KEY | FINNHUB_API_KEY | FRED_API_KEY | DESK_SEC_USER_AGENT | ALPACA_API_KEY_ID | ALPACA_API_SECRET_KEY) echo desk.env ;;
    PORKBUN_API_KEY | PORKBUN_API_SECRET_KEY) echo caddy.env ;;
    TS_AUTHKEY) echo tailscale.env ;;
    *)
      for f in $ENV_FILES; do
        if grep -qE "^(export[[:space:]]+)?$key=" "$ROOT/$f" 2>/dev/null; then
          echo "$f"
          return 0
        fi
      done
      return 1
      ;;
  esac
}

key_refusal() {
  local key=$1 value=$2
  if ! [[ "$key" =~ ^[A-Z_][A-Z0-9_]{0,63}$ ]]; then
    echo "isn't a key name"
  elif [[ "$key" =~ ^(PATH|HOME|USER|SHELL|ENV|BASH_ENV|NODE_OPTIONS|LD_.*|PYTHON.*|DESK_DATA_DIR)$ ]]; then
    echo "can't be set from the app"
  elif ! key_file_for "$key" >/dev/null; then
    echo "isn't one of the desk's keys"
  elif [ -z "$value" ]; then
    echo "is empty"
  elif [ "${#value}" -gt 1024 ]; then
    echo "is longer than 1024 characters"
  elif [[ "$value" == *$'\n'* || "$value" == *$'\r'* || "$value" == *"'"* ]]; then
    echo "can't contain a line break or a single quote"
  elif [ "$key" = ALPACA_API_KEY_ID ] && [[ "$value" != PK* ]]; then
    echo "isn't a paper key ID (paper key IDs start with PK); live keys are never allowed"
  elif [[ "$key" == *ALPACA*URL* ]] && [[ ! "$value" =~ ^https://paper-api\.alpaca\.markets(:443)?(/v2)?/?$ ]]; then
    echo "isn't Alpaca's paper API ($PAPER_URL); only paper trading is allowed"
  else
    return 1
  fi
}

key_line() {
  local key=$1 value=$2
  if [[ "$value" =~ ^[A-Za-z0-9_./:@+=,-]*$ ]]; then printf '%s=%s' "$key" "$value"; else printf "%s='%s'" "$key" "$value"; fi
}

set_env_key() {
  local key=$1 value=$2 file new
  file=$ROOT/$(key_file_for "$key") || return 1
  [ ! -L "$file" ] || return 1
  [ -e "$file" ] || (umask 077 && : >"$file")
  new=$(mktemp "$file.XXXXXX")
  chmod 600 "$new"
  KEY_LINE=$(key_line "$key" "$value") KEY_NAME=$key awk '
    $0 ~ "^(export[[:space:]]+)?" ENVIRON["KEY_NAME"] "=" { if (!done) print ENVIRON["KEY_LINE"]; done = 1; next }
    { print }
    END { if (!done) print ENVIRON["KEY_LINE"] }' "$file" >"$new"
  mv -f "$new" "$file"
  basename "$file"
}

key_names() {
  local f
  for f in $ENV_FILES; do
    [ -f "$ROOT/$f" ] && [ ! -L "$ROOT/$f" ] || continue
    sed -nE "s/^(export[[:space:]]+)?([A-Z_][A-Z0-9_]*)=.*/\\2\\t$f/p" "$ROOT/$f"
  done
}

box_keys() {
  local dir=$1 kdir=$1/keys file name req value why id result message saved=0
  if [ ! -f "$KEYS_PEM" ]; then
    (umask 077 && openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out "$KEYS_PEM" 2>/dev/null) || return 0
  fi
  chmod 600 "$KEYS_PEM"
  openssl pkey -in "$KEYS_PEM" -pubout 2>/dev/null | box_put "$dir" keys.pub
  if [ -L "$kdir" ]; then rm -f "$kdir"; fi
  [ -d "$kdir" ] || mkdir "$kdir"
  [ "$(realpath "$kdir")" = "$kdir" ] || return 0
  chown 568:568 "$kdir" 2>/dev/null || true
  for file in "$kdir"/*.req; do
    if [ -L "$file" ]; then
      rm -f "$file"
      continue
    fi
    [ -f "$file" ] || continue
    name=$(basename "$file" .req)
    req=$(head -c 8192 "$file")
    rm -f "$file"
    [[ "$name" =~ ^[A-Z_][A-Z0-9_]{0,63}$ ]] || continue
    id=$(jq -r '.id // empty' <<<"$req" 2>/dev/null | tr -cd 'a-f0-9' | head -c 32 || true)
    value=$(jq -r '.ciphertext // empty' <<<"$req" 2>/dev/null | base64 -d 2>/dev/null |
      openssl pkeyutl -decrypt -inkey "$KEYS_PEM" -pkeyopt rsa_padding_mode:oaep -pkeyopt rsa_oaep_md:sha256 -pkeyopt rsa_mgf1_md:sha256 2>/dev/null) || value=
    if [ -z "$value" ]; then
      result=failed message="The box couldn't read it; save it again"
    elif why=$(key_refusal "$name" "$value"); then
      result=refused message="$name $why"
    elif file=$(set_env_key "$name" "$value"); then
      result=saved message="Saved in $file; the desk redeploys to pick it up"
      saved=1
    else
      result=failed message="Couldn't write the env file"
    fi
    value=
    log "Key from the app: $name $result"
    jq -n --arg n "$name" --arg id "$id" --arg r "$result" --arg m "$message" --arg at "$(date -u +%FT%TZ)" \
      '{name: $n, request_id: (if $id == "" then null else $id end), result: $r, message: $m, at: $at}' | box_put "$kdir" "$name.json"
  done
  key_names | jq -R -s --arg at "$(date -u +%FT%TZ)" \
    '{checked_at: $at, present: [split("\n")[] | select(. != "") | split("\t") | {name: .[0], file: .[1]}]}' | box_put "$dir" keys.json
  if [ "$saved" -eq 1 ] && [ ! -e "$dir/requests/redeploy.json" ]; then
    jq -n --arg id "$(openssl rand -hex 6)" --arg at "$(date -u +%FT%TZ)" '{id: $id, requested_at: $at}' | box_put "$dir/requests" redeploy.json
  fi
}

# ---- Compose on the box vs the checkout ----

compose_report() {
  python3 - "$APP_CONFIGS/$APP" "$SRC/deploy/compose.yaml" "$ROOT" <<'PY' 2>/dev/null || echo '{"state": "unknown", "drift": [], "escalations": [], "missing_dirs": [], "missing_files": []}'
import glob
import json
import os
import sys

import yaml

app, main, root = sys.argv[1:4]
LOCAL = {"vektor-desk", "vektor-desk/caddy"}
HOST = ("network_mode", "pid", "ipc", "uts", "userns_mode", "cgroup")
GRANTS = ("cap_add", "devices", "security_opt", "device_cgroup_rules", "group_add")
SAFE_OPTS = {"no-new-privileges:true", "no-new-privileges"}


def load(p):
    try:
        with open(p) as f:
            return yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        return {}


def installed():
    for p in sorted(glob.glob(os.path.join(app, "versions", "*", "templates", "rendered", "*compose*.y*ml")), reverse=True):
        if load(p).get("services"):
            return load(p)
    for p in sorted(glob.glob(os.path.join(app, "versions", "*", "user_config.yaml")), reverse=True):
        cfg = load(p)
        if isinstance(cfg.get("custom_compose_config"), dict) and cfg["custom_compose_config"].get("services"):
            return cfg["custom_compose_config"]
        if isinstance(cfg.get("custom_compose_config_string"), str):
            try:
                text = yaml.safe_load(cfg["custom_compose_config_string"]) or {}
            except yaml.YAMLError:
                continue
            if text.get("services"):
                return text
    return None


def repo_of(image):
    name = str(image or "").split("@")[0]
    head, _, last = name.rpartition("/")
    last = last.split(":")[0]
    return f"{head}/{last}" if head else last


def binds(svc):
    out = []
    for v in svc.get("volumes") or []:
        if isinstance(v, str):
            src = v.split(":")[0]
        elif isinstance(v, dict):
            src = str(v.get("source") or "")
            if v.get("type") != "bind" and not src.startswith(("/", ".", "~")):
                src = ""
        else:
            src = ""
        if src and (src.startswith(("/", ".", "~")) or "/" in src):
            out.append(src)
    return out


def as_set(value):
    if isinstance(value, dict):
        return {f"{k}={v}" for k, v in value.items()}
    return {str(x) for x in value or []}


box, compose = installed(), load(main)
want = compose.get("services") or {}
if box is None or not want:
    print(json.dumps({"state": "unknown", "drift": [], "escalations": [], "missing_dirs": [], "missing_files": []}))
    sys.exit()
have = box.get("services") or {}
drift = []
for name in sorted(set(want) | set(have)):
    if name not in have:
        drift.append(f"{name} missing")
    elif name not in want:
        drift.append(f"{name} extra")
    else:
        keys = [k for k in want[name] if want[name][k] != have[name].get(k)]
        if keys:
            drift.append(f"{name}: {', '.join(keys)}")

known_repos = {repo_of(s.get("image")) for s in have.values()} | LOCAL
known_binds = {os.path.realpath(b) for s in have.values() for b in binds(s) if b.startswith("/")}
base = os.path.realpath(root)
esc, missing_dirs, missing_files = [], [], []
for name, w in sorted(want.items()):
    h = have.get(name) or {}
    if w.get("privileged"):
        esc.append(f"{name}: privileged")
    if "build" in w:
        esc.append(f"{name}: build")
    for k in HOST:
        if str(w.get(k, "")) == "host" and str(h.get(k, "")) != "host":
            esc.append(f"{name}: {k} host")
    for k in GRANTS:
        new = as_set(w.get(k)) - as_set(h.get(k)) - (SAFE_OPTS if k == "security_opt" else set())
        if new:
            esc.append(f"{name}: {k} {', '.join(sorted(new))}")
    if as_set(h.get("cap_drop")) - as_set(w.get("cap_drop")):
        esc.append(f"{name}: cap_drop loosened")
    if "user" in h and str(w.get("user")) != str(h.get("user")):
        esc.append(f"{name}: user")
    if h.get("read_only") and not w.get("read_only"):
        esc.append(f"{name}: read_only off")
    if repo_of(w.get("image")) not in known_repos:
        esc.append(f"{name}: new image {repo_of(w.get('image'))}")
    for b in binds(w):
        if not b.startswith("/") or ".." in b.split("/"):
            esc.append(f"{name}: host path {b}")
            continue
        real = os.path.realpath(b)
        if real in known_binds:
            continue
        if real != base and not real.startswith(base + "/"):
            esc.append(f"{name}: host path {b}")
        elif not os.path.exists(b):
            (missing_files if "." in os.path.basename(b) else missing_dirs).append(b)
for k, v in (compose.get("volumes") or {}).items():
    if isinstance(v, dict) and v.get("driver_opts") and v != (box.get("volumes") or {}).get(k):
        esc.append(f"volume {k}: driver_opts")
print(
    json.dumps(
        {
            "state": "drift" if drift else "current",
            "drift": drift,
            "escalations": esc,
            "missing_dirs": sorted(set(missing_dirs)),
            "missing_files": sorted(set(missing_files)),
        }
    )
)
PY
}

compose_drift() {
  local report
  report=$(compose_report)
  case $(jq -r .state <<<"$report") in
    current) echo "Compose:     matches the checkout" ;;
    unknown) echo "Compose:     couldn't read the app's installed compose under $APP_CONFIGS/$APP" ;;
    *)
      if [ "$(jq '(.escalations + .missing_files) | length' <<<"$report")" -eq 0 ]; then
        echo "Compose:     older than the checkout ($(jq -r '.drift | join("; ")' <<<"$report")): Settings → Box → Apply compose"
      else
        echo "Compose:     older than the checkout ($(jq -r '.drift | join("; ")' <<<"$report")), and the change needs your eyes ($(jq -r '(.escalations + (.missing_files | map("needs " + .))) | join("; ")' <<<"$report")): read deploy/compose.yaml, then paste it into Apps → $APP → Edit (Settings → Box has a Copy button)"
      fi
      ;;
  esac
}

compose_state() {
  local report
  report=$(compose_report)
  jq -n --arg at "$(date -u +%FT%TZ)" --argjson r "$report" --rawfile text "$SRC/deploy/compose.yaml" \
    '$r + {checked_at: $at, can_apply: ($r.state == "drift" and (($r.escalations + $r.missing_files) | length) == 0), compose: (if $r.state == "drift" then $text else null end)}' 2>/dev/null ||
    jq -n --arg at "$(date -u +%FT%TZ)" --argjson r "$report" '$r + {checked_at: $at, can_apply: false, compose: null}'
}

at_main() {
  local head
  if [ -n "$(repo status --porcelain --untracked-files=no 2>/dev/null)" ]; then
    echo "The checkout at $SRC has local edits, so it isn't main. Nothing was changed"
    return 1
  fi
  head=$(repo rev-parse HEAD 2>/dev/null) || {
    echo "Can't read the checkout at $SRC"
    return 1
  }
  if [ "$head" != "$(repo rev-parse "origin/$BRANCH" 2>/dev/null)" ]; then
    echo "The checkout (${head:0:7}) isn't at main yet; auto-deploy catches up within 5 minutes. Try again then"
    return "$BUSY"
  fi
}

apply_compose() {
  local report head why d files payload rc ALERTS="Apply compose stopped"
  at_main || {
    rc=$?
    return "$rc"
  }
  head=$(repo rev-parse HEAD)
  if [ "$(live_build vektor-desk-api)" != "$head" ]; then
    echo "The live build isn't main's ${head:0:7} yet; auto-deploy catches up within 5 minutes. Try again then"
    return "$BUSY"
  fi
  report=$(compose_report)
  case $(jq -r .state <<<"$report") in
    current)
      echo "Compose already matches main"
      return 0
      ;;
    unknown)
      echo "Couldn't read the app's installed compose under $APP_CONFIGS/$APP. Nothing was changed"
      return 1
      ;;
  esac
  echo "Differs: $(jq -r '.drift | join("; ")' <<<"$report")"
  if [ "$(jq '.escalations | length' <<<"$report")" -gt 0 ]; then
    echo "Not applied from the app: the change widens what containers can do ($(jq -r '.escalations | join("; ")' <<<"$report"))."
    echo "Read deploy/compose.yaml, then paste it into Apps → $APP → Edit (Settings → Box has a Copy button)"
    return 1
  fi
  if [ "$(jq '.missing_files | length' <<<"$report")" -gt 0 ]; then
    echo "Not applied: it needs files that aren't there yet ($(jq -r '.missing_files | join(", ")' <<<"$report")). Run setup-truenas.sh first"
    return 1
  fi
  if docker compose version >/dev/null 2>&1 && ! docker compose -f "$SRC/deploy/compose.yaml" config -q 2>&1; then
    echo "deploy/compose.yaml at ${head:0:7} doesn't pass docker compose config. Nothing was changed"
    return 1
  fi
  if why=$(busy); then
    echo "A desk job is running: $why. Nothing was changed"
    return "$BUSY"
  fi
  while IFS= read -r d; do
    [ -n "$d" ] || continue
    mkdir -p "$d"
    chown 568:568 "$d"
    echo "Made $d"
  done < <(jq -r '.missing_dirs[]' <<<"$report")
  files=$(backup) || {
    echo "The backup failed, so nothing was changed"
    return 1
  }
  log "Backed up: $files"
  payload=$(jq -n --rawfile c "$SRC/deploy/compose.yaml" '{custom_compose_config_string: $c}')
  log "Applying deploy/compose.yaml at ${head:0:7} to $APP"
  if ! run_job app.update "$APP" "$payload"; then
    echo "TrueNAS didn't take the update (see $BUILD_LOG). Paste deploy/compose.yaml into Apps → $APP → Edit instead (Settings → Box has a Copy button)"
    alert "$ALERTS" "TrueNAS didn't take the compose update. Paste it by hand; Settings, Box has a Copy button."
    return 1
  fi
  if ! healthy "$head"; then
    echo "$APP didn't come back healthy within ${HEALTH_WAIT}s of the update. See the app's logs"
    alert "$ALERTS" "$APP didn't come back healthy after the compose update."
    return 1
  fi
  log "Compose applied at ${head:0:7}"
  [ "$(compose_report | jq -r .state)" = current ] || echo "TrueNAS took it, but its installed compose still reads differently; check Apps → $APP → Edit"
  app_card >/dev/null 2>&1 || true
}

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
      ;;
    backup)
      ALERTS="Nightly backup failed"
      files=$(backup) || die "the backup failed"
      log "Backed up: $files"
      ;;
    auto)
      auto
      exec 9>&-
      app_card >/dev/null 2>&1 || true
      logs_export || true
      box_requests || true
      ;;
    box) box_requests ;;
    redeploy)
      exec 9>"$LOCK"
      flock -n 9 || die "a deploy is already running: tail -f $LOG"
      redeploy
      ;;
    card) app_card ;;
    logs) logs_export ;;
    status) status ;;
    restore-test) restore_test ;;
    check) check ;;
    update-script) update_script ;;
    apply-compose)
      exec 9>"$LOCK"
      flock -n 9 || die "a deploy is already running: tail -f $LOG" "$BUSY"
      apply_compose
      ;;
    *)
      echo "usage: deploy.sh [now | auto | status | backup | restore-test | check | logs | card | redeploy | box | update-script | apply-compose]" >&2
      exit 2
      ;;
  esac
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then main "$@"; fi
