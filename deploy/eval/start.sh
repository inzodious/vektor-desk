#!/bin/sh
# The eval container's start (docs/eval-access.md): rules file, wait for a sign-in, answer the trust and Remote Control
# prompts once (no TTY here), then Remote Control with a debug log that deploy.sh logs exports, redacted.
set -eu
SRC=${EVAL_SRC:-/src}
WORK=${EVAL_WORK:-/work}
LOG=$HOME/logs/remote-control.log

# ---- Feature flags on ----
unset DISABLE_TELEMETRY DO_NOT_TRACK CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC

cp "$SRC/deploy/eval/CLAUDE.md" "$WORK/CLAUDE.md"
until [ -s "$HOME/.claude/.credentials.json" ]; do sleep "${EVAL_WAIT:-30}"; done
python - "$HOME/.claude.json" "$WORK" <<'PY'
import json
import os
import sys

path, work = sys.argv[1:3]
try:
    with open(path) as f:
        data = json.load(f)
except (OSError, ValueError):
    data = {}
project = data.setdefault("projects", {}).setdefault(work, {})
if project.get("hasTrustDialogAccepted") is not True or data.get("remoteDialogSeen") is not True:
    project["hasTrustDialogAccepted"] = True
    data["remoteDialogSeen"] = True
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)
os.chmod(path, 0o600)
PY
mkdir -p "$HOME/logs"
if [ -f "$LOG" ]; then mv -f "$LOG" "$LOG.1"; fi

# ---- Paused while the box is in low-memory mode ----
if python -c "import desk.memory" 2>/dev/null; then
  exec python -m desk.memory hold --name "the eval session" --data "${EVAL_DATA:-/data}" -- claude remote-control --name vektor-desk-eval --debug-file "$LOG"
fi
exec claude remote-control --name vektor-desk-eval --debug-file "$LOG"
