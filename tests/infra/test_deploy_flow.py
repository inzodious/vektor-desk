import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[2] / "deploy" / "deploy.sh"
API, CADDY = "vektor-desk-api", "vektor-desk-caddy"
WHY = "desk.db copy failed its check: NULL value in quotes_live.at"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None or shutil.which("jq") is None, reason="needs bash and jq, like the box")

STUBS = r"""
key() { printf '%s' "$1" | tr '/:' '__'; }
image_build() { cat "$S/tag.$(key "$1")" 2>/dev/null || true; }
live_build() { cat "$S/run.$1" 2>/dev/null || true; }
running_image() { if [ -f "$S/run.$1" ]; then echo "id:$(cat "$S/run.$1")"; fi; }
health() {
  [ "$1" != vektor-desk-cron ] || { echo running; return 0; }
  [ -f "$S/run.$1" ] || { echo missing; return 0; }
  if [ "$(cat "$S/run.$1")" = "$(cat "$S/bad-build" 2>/dev/null)" ]; then echo unhealthy; return 0; fi
  if [ "$1" = vektor-desk-api ]; then echo healthy; else echo running; fi
}
busy() { return 1; }
app_state() { cat "$S/app"; }
update_checkout() { :; }
repo() { case "$1" in rev-parse) cat "$S/head" ;; diff) return 0 ;; log) echo subject ;; esac; }
alert() { echo "$1: $2" >>"$S/alerts"; }
app_card() { :; }
backup() {
  if [ -e "$S/backup-fails" ]; then
    echo "$WHY" >"$BACKUP_WHY"
    return 1
  fi
  echo "backup${1:+ $1}" >>"$S/calls"
  echo backup.tar.gz
}
restart_app() {
  echo restart >>"$S/calls"
  cp "$S/tag.$(key vektor-desk:local)" "$S/run.vektor-desk-api"
  cp "$S/tag.$(key vektor-desk/caddy:local)" "$S/run.vektor-desk-caddy"
}
docker() {
  case "$1" in
    build)
      if [ "$2" = --target ]; then
        echo "stage $3" >>"$S/calls"
        if [ "$3" = "$(cat "$S/starved-stage" 2>/dev/null)" ]; then
          echo "oom_kill 8" >"$S/vmstat"
          return 1
        fi
        [ "$3" != "$(cat "$S/broken-stage" 2>/dev/null)" ] || return 1
        return 0
      fi
      echo "build $7" >>"$S/calls"
      echo "${3#DESK_BUILD=}" >"$S/tag.$(key "$7")"
      ;;
    tag) if [[ "$2" == id:* ]]; then echo "${2#id:}" >"$S/tag.$(key "$3")"; else cp "$S/tag.$(key "$2")" "$S/tag.$(key "$3")"; fi ;;
    rmi) rm -f "$S/tag.$(key "$2")" ;;
  esac
}
LOG=$S/deploy.log
LOCK=$S/lock
"""


class Box:
    def __init__(self, tmp_path: Path, running: str, local: str, head: str, app: str = "RUNNING"):
        self.dir = tmp_path / "state"
        self.dir.mkdir()
        (tmp_path / "root").mkdir()
        self.env = {"DESK_ROOT": str(tmp_path / "root"), "DESK_HEALTH_WAIT": "1", "S": str(self.dir), "WHY": WHY, "PATH": "/usr/local/bin:/usr/bin:/bin"}
        (self.dir / "app").write_text(app)
        (self.dir / "head").write_text(head)
        if running:
            for c in (API, CADDY):
                (self.dir / f"run.{c}").write_text(running)
        if local:
            self.tag("vektor-desk:local", local)
            self.tag("vektor-desk/caddy:local", local)

    def tag(self, name: str, build: str | None = None) -> str:
        path = self.dir / ("tag." + name.replace("/", "_").replace(":", "_"))
        if build is not None:
            path.write_text(build)
        return path.read_text().strip() if path.exists() else ""

    def running(self) -> str:
        return (self.dir / f"run.{API}").read_text().strip()

    def calls(self) -> list[str]:
        path = self.dir / "calls"
        return path.read_text().splitlines() if path.exists() else []

    def log(self) -> str:
        return (self.dir / "deploy.log").read_text()

    def run(self, fn: str = "deploy") -> subprocess.CompletedProcess:
        return subprocess.run(["bash", "-c", f'source "{DEPLOY}"; {STUBS}\n{fn}'], capture_output=True, text=True, env=self.env, timeout=60)


def test_deploy_backs_up_then_swaps_images_and_keeps_what_was_running_as_previous(tmp_path):
    box = Box(tmp_path, running="aaa", local="aaa", head="bbb")
    res = box.run()
    assert res.returncode == 0, res.stdout + res.stderr
    assert box.calls() == ["build vektor-desk:candidate", "build vektor-desk/caddy:candidate", "backup vektor-desk:candidate", "restart"]
    assert box.running() == "bbb" and box.tag("vektor-desk:local") == "bbb" and box.tag("vektor-desk:previous") == "aaa"
    assert box.tag("vektor-desk:candidate") == "" and "Live: bbb" in box.log()
    again = box.run()
    assert again.returncode == 0 and "Already live: bbb" in box.log() and box.calls().count("restart") == 1


def test_a_failed_backup_changes_no_image_and_the_next_try_reuses_the_build(tmp_path):
    box = Box(tmp_path, running="aaa", local="aaa", head="bbb")
    (box.dir / "backup-fails").touch()
    res = box.run()
    assert res.returncode == 1
    assert f"the backup failed ({WHY}), so nothing was changed" in box.log()
    assert box.tag("vektor-desk:local") == "aaa" and box.tag("vektor-desk:candidate") == "bbb" and box.running() == "aaa"
    assert "restart" not in box.calls()
    (box.dir / "backup-fails").unlink()
    res = box.run()
    assert res.returncode == 0, res.stdout + res.stderr
    assert [c for c in box.calls() if c.startswith("build")] == ["build vektor-desk:candidate", "build vektor-desk/caddy:candidate"]
    assert box.running() == "bbb" and box.tag("vektor-desk:previous") == "aaa"


def test_a_build_that_was_tagged_but_never_started_still_goes_live(tmp_path):
    box = Box(tmp_path, running="aaa", local="bbb", head="bbb")
    box.tag("vektor-desk:previous", "zzz")
    res = box.run()
    assert res.returncode == 0, res.stdout + res.stderr
    assert "Already live" not in box.log() and box.calls() == ["backup vektor-desk:local", "restart"]
    assert box.running() == "bbb" and box.tag("vektor-desk:previous") == "aaa"


def test_an_unhealthy_deploy_goes_back_to_the_images_that_were_running(tmp_path):
    box = Box(tmp_path, running="aaa", local="bbb", head="ccc")
    (box.dir / "bad-build").write_text("ccc")
    res = box.run()
    assert res.returncode == 1 and "rolled back; the previous version is live again" in box.log()
    assert box.running() == "aaa" and box.tag("vektor-desk:local") == "aaa" and box.calls().count("restart") == 2


def test_first_install_only_tags_the_images(tmp_path):
    box = Box(tmp_path, running="", local="", head="bbb", app="MISSING")
    res = box.run()
    assert res.returncode == 0, res.stdout + res.stderr
    assert box.tag("vektor-desk:local") == "bbb" and box.calls() == ["build vektor-desk:candidate", "build vektor-desk/caddy:candidate"]


def test_redeploy_refuses_to_start_a_build_that_never_ran(tmp_path):
    box = Box(tmp_path, running="aaa", local="bbb", head="bbb")
    res = box.run("redeploy")
    assert res.returncode == 1 and "isn't running yet" in box.log() and box.calls() == []
    (tmp_path / "same").mkdir()
    same = Box(tmp_path / "same", running="aaa", local="aaa", head="aaa")
    assert same.run("redeploy").returncode == 0 and same.calls() == ["restart"]


def test_a_commit_held_back_by_a_failed_backup_retries_after_a_good_backup(tmp_path):
    box = Box(tmp_path, running="aaa", local="aaa", head="bbb")
    root = tmp_path / "root"
    (box.dir / "backup-fails").touch()
    assert box.run("auto").returncode == 1
    assert (root / "deploy-auto.failed").read_text().strip() == "bbb" and (root / "deploy-auto.failed.why").read_text().strip() == "backup"
    assert (box.dir / "alerts").read_text().startswith(f"Auto-deploy stopped: the backup failed ({WHY})")
    assert box.run("auto").returncode == 0 and box.running() == "aaa" and len(box.calls()) == 2
    assert "because its backup failed" in box.run("status 2>/dev/null || true").stdout
    (box.dir / "backup-fails").unlink()
    assert box.run("backup_now").returncode == 0
    assert not (root / "deploy-auto.failed").exists() and "auto-deploy retries" in box.log()
    assert box.run("auto").returncode == 0 and box.running() == "bbb"


def test_a_commit_held_back_for_another_reason_waits_for_a_push_or_deploy_now(tmp_path):
    box = Box(tmp_path, running="aaa", local="aaa", head="bbb")
    root = tmp_path / "root"
    (box.dir / "bad-build").write_text("bbb")
    assert box.run("auto").returncode == 1
    assert (root / "deploy-auto.failed.why").read_text().strip() == "deploy" and box.running() == "aaa"
    assert box.run("backup_now").returncode == 0 and (root / "deploy-auto.failed").exists()
    (box.dir / "bad-build").unlink()
    assert box.run("auto").returncode == 0 and box.running() == "aaa"
    assert box.run("deploy").returncode == 0 and box.running() == "bbb" and not (root / "deploy-auto.failed").exists()


def test_a_new_box_script_retries_the_commit_an_older_script_held_back(tmp_path):
    box = Box(tmp_path, running="aaa", local="aaa", head="bbb")
    root = tmp_path / "root"
    (box.dir / "bad-build").write_text("bbb")
    assert box.run("auto").returncode == 1
    assert len((root / "deploy-auto.failed.script").read_text().strip()) == 64
    (box.dir / "bad-build").unlink()
    assert box.run("auto").returncode == 0 and box.running() == "aaa"
    (root / "deploy-auto.failed.script").unlink()
    assert box.run("auto").returncode == 0 and box.running() == "bbb" and "The box script changed since bbb was held back" in box.log()
    (tmp_path / "next").mkdir()
    again = Box(tmp_path / "next", running="aaa", local="bbb", head="bbb")
    for name, text in (("deploy-auto.failed", "bbb"), ("deploy-auto.failed.why", "backup"), ("deploy-auto.failed.script", "0" * 64)):
        (tmp_path / "next" / "root" / name).write_text(text + "\n")
    assert again.run("auto").returncode == 0 and again.running() == "bbb" and again.calls() == ["backup vektor-desk:local", "restart"]


def test_the_pre_deploy_backup_runs_on_the_new_build_and_the_nightly_one_in_the_running_container(tmp_path):
    root = tmp_path / "root"
    (root / "data").mkdir(parents=True)
    env = {"DESK_ROOT": str(root), "DESK_BACKUPS": str(tmp_path / "backups"), "PATH": "/usr/local/bin:/usr/bin:/bin"}
    script = f"""source "{DEPLOY}"; LOG={tmp_path}/deploy.log
docker() {{ if [ "$1" = inspect ]; then echo true; else echo "$*" >>{tmp_path}/docker; mkdir -p {root}/data/backup-staging; echo '{{"ok": true}}'; fi; }}
backup vektor-desk:candidate >/dev/null && backup >/dev/null"""
    res = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env, timeout=30)
    assert res.returncode == 0, res.stdout + res.stderr
    first, second = (tmp_path / "docker").read_text().splitlines()
    assert first.startswith("run --rm --network none --user 568:568") and "vektor-desk:candidate python -m desk.backup --out /data/backup-staging" in first
    assert second == "exec vektor-desk-cron python -m desk.backup --out /data/backup-staging"


def test_backup_keeps_the_reason_for_the_alert(tmp_path):
    root = tmp_path / "root"
    (root / "data").mkdir(parents=True)
    env = {"DESK_ROOT": str(root), "PATH": "/usr/local/bin:/usr/bin:/bin"}
    script = f"""source "{DEPLOY}"; LOG={tmp_path}/deploy.log
docker() {{ if [ "$1" = inspect ]; then echo true; else echo 'Traceback noise'; echo '{{"ok": false, "error": "{WHY}"}}'; return 1; fi; }}
backup || echo "rc=$?"; backup_why"""
    res = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env, timeout=30)
    assert res.stdout.splitlines() == ["rc=1", WHY]
    assert WHY in (tmp_path / "deploy.log").read_text()


@pytest.mark.skipif(os.geteuid() != 0, reason="deploy.sh runs as root, like the box")
def test_auto_still_checks_in_and_runs_box_work_when_the_deploy_stops(tmp_path):
    root = tmp_path / "root"
    (root / "data" / "run").mkdir(parents=True)
    stub = tmp_path / "self.sh"
    stub.write_text('echo "$1" >> ' + str(tmp_path / "calls") + "\nexit 1\n")
    env = {"DESK_ROOT": str(root), "DESK_SELF": str(stub), "DESK_PINNED": str(tmp_path / "none"), "PATH": "/usr/local/bin:/usr/bin:/bin"}
    res = subprocess.run(["bash", str(DEPLOY), "auto"], capture_output=True, text=True, env=env, timeout=60)
    assert res.returncode == 1
    assert (tmp_path / "calls").read_text().split() == ["auto-deploy"]
    assert (root / "data" / "run" / "box" / "host.alive").read_text().strip().endswith("Z")
    assert not (root / "data" / "run" / "logs" / "eval-debug.log").exists()


def staged(tmp_path: Path) -> Box:
    box = Box(tmp_path, running="aaa", local="aaa", head="bbb")
    src = tmp_path / "src"
    (src / "deploy" / "caddy").mkdir(parents=True)
    shutil.copy(DEPLOY.parents[1] / "Dockerfile", src / "Dockerfile")
    shutil.copy(DEPLOY.parent / "caddy" / "Dockerfile", src / "deploy" / "caddy" / "Dockerfile")
    (box.dir / "vmstat").write_text("nr_free_pages 1\noom_kill 7\n")
    (box.dir / "meminfo").write_text("MemTotal: 15728640 kB\nMemAvailable: 524288 kB\n")
    box.env |= {"DESK_SRC": str(src), "DESK_VMSTAT": str(box.dir / "vmstat"), "DESK_MEMINFO": str(box.dir / "meminfo")}
    return box


def test_the_image_builds_one_stage_at_a_time_before_the_whole(tmp_path):
    box = staged(tmp_path)
    res = box.run()
    assert res.returncode == 0, res.stdout + res.stderr
    builds = [c for c in box.calls() if c.startswith(("stage", "build"))]
    assert builds[:4] == ["stage node", "stage ui", "stage deps", "build vektor-desk:candidate"]
    assert builds[-1] == "build vektor-desk/caddy:candidate" and all(c.startswith("stage") for c in builds[4:-1])
    assert "one stage at a time" in box.log() and box.running() == "bbb"
    log = (tmp_path / "root" / "deploy-build.log").read_text()
    assert "(512 MB free)" in log and "---- stage ui" in log and "---- image" in log


def test_a_build_the_box_ran_out_of_memory_for_says_so_and_touches_nothing(tmp_path):
    box = staged(tmp_path)
    (box.dir / "starved-stage").write_text("ui")
    res = box.run("auto")
    assert res.returncode == 1
    assert "the box ran out of memory building vektor-desk:local (512 MB free now), so nothing was changed" in box.log()
    assert "Auto-deploy stopped" in (box.dir / "alerts").read_text()
    assert box.running() == "aaa" and "restart" not in box.calls() and "build vektor-desk:candidate" not in box.calls()
    assert (tmp_path / "root" / "deploy-auto.failed.why").read_text().strip() == "memory"


def test_a_build_that_breaks_for_another_reason_keeps_its_own_words(tmp_path):
    box = staged(tmp_path)
    (box.dir / "broken-stage").write_text("deps")
    res = box.run()
    assert res.returncode == 1 and "vektor-desk:local didn't build; the live app wasn't touched" in box.log()
    assert "out of memory" not in box.log()


HEAD = "truenas kernel: oom-kill:constraint="
TAIL = ",nodemask=(null),cpuset=/,mems_allowed=0,"
SCOPE = "/system.slice/docker-{cron}.scope"
JOURNAL = f"""2026-11-11T14:03:22-0500 truenas kernel: node invoked oom-killer: gfp_mask=0xcc0(GFP_KERNEL), order=0, oom_score_adj=0
2026-11-11T14:03:22-0500 {HEAD}CONSTRAINT_MEMCG{TAIL}oom_memcg={SCOPE},task_memcg={SCOPE},task=node,pid=4242,uid=568
2026-11-11T15:10:00-0500 {HEAD}CONSTRAINT_NONE{TAIL}global_oom,task_memcg=/docker/{{lab}},task=python,pid=77,uid=568
2026-11-11T15:20:00-0500 {HEAD}CONSTRAINT_NONE{TAIL}global_oom,task_memcg=/system.slice/smbd.service,task=smbd,pid=9,uid=0
2026-11-11T15:30:00-0500 {HEAD}CONSTRAINT_MEMCG{TAIL}oom_memcg=/docker/{{other}},task_memcg=/docker/{{other}},task=java,pid=5,uid=0
garbage oom-kill:constraint=CONSTRAINT_NONE without a time
"""


def test_the_host_reports_who_was_stopped_for_memory(tmp_path):
    ids = {"cron": "a" * 64, "lab": "b" * 64, "other": "c" * 64}
    (tmp_path / "journal").write_text(JOURNAL.format(**ids))
    script = f"""source "{DEPLOY}"
journalctl() {{ cat {tmp_path}/journal; }}
docker() {{ printf '%s vektor-desk-cron\n%s vektor-desk-lab\n' {ids["cron"]} {ids["lab"]}; }}
memory_state"""
    res = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env={"PATH": "/usr/local/bin:/usr/bin:/bin"}, timeout=30)
    assert res.returncode == 0, res.stderr
    report = json.loads(res.stdout)
    assert report["checked_at"].endswith("Z")
    assert report["kills"] == [
        {"at": "2026-11-11T19:03:22Z", "process": "node", "scope": "cap", "service": "cron"},
        {"at": "2026-11-11T20:10:00Z", "process": "python", "scope": "box", "service": "lab"},
        {"at": "2026-11-11T20:20:00Z", "process": "smbd", "scope": "box", "service": ""},
    ]


def test_the_host_report_is_empty_not_broken_without_a_journal(tmp_path):
    script = f"""source "{DEPLOY}"
journalctl() {{ return 1; }}
docker() {{ return 1; }}
memory_state"""
    res = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env={"PATH": "/usr/local/bin:/usr/bin:/bin"}, timeout=30)
    assert res.returncode == 0 and json.loads(res.stdout)["kills"] == []


# ---- Images from a builder on another machine ----

BUILD_STUBS = r"""
eval "$(declare -f docker | sed '1s/^docker/docker_base/')"
docker() {
  case "$1" in
    load)
      read -r t l < <(gzip -dc "$3")
      echo "$l" >"$S/tag.$(key "vektor-desk:built-$t")"
      echo load >>"$S/calls"
      ;;
    image) cat "$S/arch" 2>/dev/null || echo amd64 ;;
    version) echo amd64 ;;
    *) docker_base "$@" ;;
  esac
}
repo() {
  case "$1" in
    rev-parse) cat "$S/head" ;;
    diff) return 0 ;;
    archive) echo source >"$4" ;;
    log) if [ "$3" = --format=%ct ]; then cat "$S/landed" 2>/dev/null || true; else echo subject; fi ;;
  esac
}
"""


class BuiltBox(Box):
    def __init__(self, tmp_path: Path, running: str = "aaa", local: str = "aaa", head: str = "bbb", approved: bool = True):
        from desk.worker import builder

        super().__init__(tmp_path, running, local, head)
        self.root = tmp_path / "root"
        self.inbox = self.root / "data" / "run" / "box" / "build" / "in"
        self.inbox.mkdir(parents=True)
        self.pending = self.inbox.parent / "pending"
        self.pending.mkdir()
        self.src = tmp_path / "src"
        (self.src / "deploy").mkdir(parents=True)
        self.pinned = tmp_path / "pin" / "builders"
        self.pinned.mkdir(parents=True)
        self.key, self.pub = builder.key_pair(tmp_path / "work")
        self.mark = builder.fingerprint(self.pub)
        self.env |= {"DESK_SRC": str(self.src), "DESK_PINNED": str(tmp_path / "pin" / "deploy.sh")}
        if approved:
            (self.pinned / f"{self.mark}.pub").write_text(self.pub)

    def send(self, commit: str, label: str | None = None, signed_for: str | None = None, key: Path | None = None) -> None:
        import gzip
        import hashlib

        from desk.worker import builder

        image = gzip.compress(f"{commit} {label or commit}\n".encode())
        (self.inbox / f"{commit}.tar.gz").write_bytes(image)
        said = builder.sign(key or self.key, builder.statement(signed_for or commit, hashlib.sha256(image).hexdigest()))
        (self.inbox / f"{commit}.sig").write_text(said + "\n")

    def alive(self, age: int = 0) -> None:
        from datetime import UTC, datetime, timedelta

        at = (datetime.now(UTC) - timedelta(seconds=age)).strftime("%Y-%m-%dT%H:%M:%SZ")
        (self.inbox.parent / "builder.alive").write_text(json.dumps({"at": at, "fingerprint": self.mark, "name": "Horizon"}))

    def last(self) -> dict:
        return json.loads((self.root / "deploy-build.last").read_text())

    def alerts(self) -> str:
        path = self.dir / "alerts"
        return path.read_text() if path.exists() else ""

    def run(self, fn: str = "deploy") -> subprocess.CompletedProcess:
        return subprocess.run(["bash", "-c", f'source "{DEPLOY}"; {STUBS}\n{BUILD_STUBS}\n{fn}'], capture_output=True, text=True, env=self.env, timeout=60)


needs_openssl = pytest.mark.skipif(shutil.which("openssl") is None, reason="needs openssl, like the box")


@needs_openssl
def test_deploy_takes_an_image_signed_by_an_approved_builder_and_builds_nothing_itself(tmp_path):
    box = BuiltBox(tmp_path)
    box.send("bbb")
    res = box.run()
    assert res.returncode == 0, res.stdout + res.stderr
    assert box.calls() == ["load", "build vektor-desk/caddy:candidate", "backup vektor-desk:candidate", "restart"]
    assert box.running() == "bbb" and box.tag("vektor-desk:local") == "bbb" and box.tag("vektor-desk:previous") == "aaa"
    assert box.tag("vektor-desk:built-bbb") == "" and box.tag("vektor-desk:candidate") == ""
    assert f"Using the image a builder made for bbb (signed by {box.mark[:12]})" in box.log()
    assert box.last()["how"] == "builder" and box.last()["commit"] == "bbb" and box.last()["why"] is None
    assert list(box.inbox.iterdir()) == [] and not list(box.root.glob(".built.*")) and box.alerts() == ""
    assert "1 approved; last image bbb came from a builder" in box.run("builder_line").stdout


@needs_openssl
@pytest.mark.parametrize(
    ("how", "why"),
    [
        ("forged", "it isn't signed by an approved builder for this commit"),
        ("replayed", "it isn't signed by an approved builder for this commit"),
        ("stranger", "it isn't signed by an approved builder for this commit"),
        ("mislabelled", "the image inside isn't the build of this commit"),
        ("other-arch", "it was built for another kind of processor"),
        ("garbled", "its signature isn't readable"),
    ],
)
def test_an_image_the_box_cannot_trust_is_refused_and_built_here(tmp_path, how, why):
    from desk.worker import builder

    box = BuiltBox(tmp_path)
    if how == "forged":
        box.send("bbb")
        (box.inbox / "bbb.tar.gz").write_bytes((box.inbox / "bbb.tar.gz").read_bytes() + b"\0")
    elif how == "replayed":
        box.send("bbb", signed_for="aaa")
    elif how == "stranger":
        box.send("bbb", key=builder.key_pair(tmp_path / "stranger")[0])
    elif how == "mislabelled":
        box.send("bbb", label="ccc")
    elif how == "other-arch":
        box.send("bbb")
        (box.dir / "arch").write_text("arm64\n")
    else:
        box.send("bbb")
        (box.inbox / "bbb.sig").write_text("@@@ not base64 @@@\n")
    res = box.run()
    assert res.returncode == 0, res.stdout + res.stderr
    assert [c for c in box.calls() if c != "load"] == [
        "build vektor-desk:candidate",
        "build vektor-desk/caddy:candidate",
        "backup vektor-desk:candidate",
        "restart",
    ]
    assert ("load" in box.calls()) == (how in ("mislabelled", "other-arch"))
    assert box.running() == "bbb" and box.tag("vektor-desk:built-bbb") == ""
    assert f"The builder's image for bbb was refused: {why}. Building it here" in box.log()
    assert box.alerts().startswith(f"Desk refused a built image: The image a builder sent for bbb was refused: {why}.")
    assert box.last() == {"commit": "bbb", "how": "box", "why": f"the builder's image was refused: {why}", "at": box.last()["at"]}
    assert list(box.inbox.iterdir()) == [] and not list(box.root.glob(".built.*"))


@needs_openssl
def test_a_signed_image_is_ignored_until_its_builder_is_approved(tmp_path):
    box = BuiltBox(tmp_path, approved=False)
    box.send("bbb")
    assert box.run().returncode == 0
    assert box.calls() == ["build vektor-desk:candidate", "build vektor-desk/caddy:candidate", "backup vektor-desk:candidate", "restart"]
    assert box.alerts() == "" and box.last()["how"] == "box" and "none approved" in box.run("builder_line").stdout


@needs_openssl
def test_a_builder_that_reports_a_failure_hands_the_build_back_to_the_box(tmp_path):
    box = BuiltBox(tmp_path)
    (box.inbox / "bbb.failed").write_text(json.dumps({"at": "x", "error": "docker build stopped: npm ERR! out of luck"}))
    assert box.run().returncode == 0
    assert box.calls()[0] == "build vektor-desk:candidate" and box.running() == "bbb"
    assert "The builder couldn't make bbb (docker build stopped: npm ERR! out of luck); building it here" in box.log()


@needs_openssl
def test_approve_builder_pins_only_keys_whose_fingerprint_is_listed_in_main(tmp_path):
    from desk.worker import builder

    box = BuiltBox(tmp_path, approved=False)
    listing = box.src / "deploy" / "builders.txt"
    pin = box.pinned / f"{box.mark}.pub"
    (box.pending / f"{box.mark}.pub").write_text(box.pub)
    (box.pending / f"{box.mark}.json").write_text("{}")
    none = box.run("approve_builder")
    assert none.returncode == 0 and "lists no builder" in none.stdout and not pin.exists()
    listing.write_text(f"# builders\n{box.mark} Horizon\nnot-a-fingerprint Mallory\n")
    other = builder.fingerprint(builder.key_pair(tmp_path / "other")[1])
    (box.pending / f"{other}.pub").write_text(box.pub)
    listing.write_text(listing.read_text() + f"{other} Spare\n{'0' * 64} Ghost\n")
    res = box.run("approve_builder")
    assert res.returncode == 0, res.stdout + res.stderr
    assert pin.read_text() == box.pub and pin.stat().st_mode & 0o777 == 0o600 and [p.name for p in box.pinned.iterdir()] == [pin.name]
    assert f"Approved Horizon ({box.mark[:12]})" in res.stdout and "Mallory" not in res.stdout
    assert f"Spare ({other[:12]}): the key that was sent doesn't match the fingerprint in main. Not approved" in res.stdout
    assert "Ghost (000000000000) is listed in main, but its builder hasn't sent that key yet" in res.stdout
    assert not (box.pending / f"{box.mark}.pub").exists() and box.alerts().startswith("Desk approved a builder: Horizon can now build the desk's images.")
    again = box.run("approve_builder")
    assert f"Horizon ({box.mark[:12]}) is already approved" in again.stdout and box.alerts().count("approved a builder") == 1
    state = json.loads(box.run("builder_state").stdout)
    assert state["approved"] == [{"fingerprint": box.mark, "name": "Horizon"}] and state["wait_seconds"] == 1200 and state["settle_seconds"] == 600
    assert [(r["name"], r["approved"]) for r in state["listed"]] == [("Horizon", True), ("Spare", False), ("Ghost", False)]
    listing.write_text("# nobody\n")
    gone = box.run("approve_builder")
    assert f"Removed {box.mark[:12]}" in gone.stdout and not pin.exists()
    (box.root / "deploy.no-self-pin").touch()
    off = box.run("approve_builder")
    assert off.returncode == 1 and "Approving from the app is off" in off.stdout


@needs_openssl
def test_auto_asks_the_builder_waits_while_it_works_and_deploys_its_image(tmp_path):
    box = BuiltBox(tmp_path)
    box.alive()
    assert box.run("auto").returncode == 0
    want = json.loads((box.inbox.parent / "want.json").read_text())
    assert (
        want["commit"] == "bbb"
        and want["source"] == "bbb.src.tar.gz"
        and (box.inbox.parent / "bbb.src.tar.gz").read_text() == "source\n"
        and len(want["sha256"]) == 64
    )
    assert box.running() == "aaa" and box.calls() == []
    assert "Asked the builder for bbb" in box.log() and "Auto-deploy is waiting for bbb: the builder is making its image (asked 0 min ago" in box.log()
    assert box.run("auto").returncode == 0 and box.log().count("Asked the builder") == 1 and box.log().count("is waiting for bbb") == 1
    box.send("bbb")
    assert box.run("auto").returncode == 0
    assert box.running() == "bbb" and box.calls() == ["load", "build vektor-desk/caddy:candidate", "backup vektor-desk:candidate", "restart"]
    assert (
        not (box.inbox.parent / "want.json").exists() and not (box.root / "deploy-build.asked").exists() and not (box.inbox.parent / "bbb.src.tar.gz").exists()
    )


@needs_openssl
@pytest.mark.parametrize("how", ["asleep", "slow", "stranger", "nobody"])
def test_auto_builds_here_at_once_when_no_builder_is_working_on_it(tmp_path, how):
    box = BuiltBox(tmp_path, approved=how != "nobody")
    if how == "asleep":
        box.alive(age=600)
    elif how == "slow":
        box.alive()
        (box.root / "deploy-build.asked").write_text("bbb 1000\n")
    elif how == "stranger":
        (box.inbox.parent / "builder.alive").write_text(json.dumps({"at": "2099-01-01T00:00:00Z", "fingerprint": "0" * 64, "name": "Mallory"}))
    else:
        box.alive()
    assert box.run("auto").returncode == 0
    assert box.running() == "bbb" and box.calls()[0] == "build vektor-desk:candidate" and box.last()["how"] == "box"
    assert ("Asked the builder for bbb" in box.log()) == (how in ("asleep", "stranger"))


def test_auto_lets_main_settle_so_commits_that_land_together_become_one_deploy(tmp_path):
    import time

    box = BuiltBox(tmp_path, approved=False) if shutil.which("openssl") else None
    if box is None:
        pytest.skip("needs openssl")
    (box.dir / "landed").write_text(f"{int(time.time()) - 125}\n")
    assert box.run("auto").returncode == 0
    assert box.running() == "aaa" and box.calls() == []
    assert "Auto-deploy is letting main settle before bbb: it landed 2 min ago, and a deploy waits until main has been quiet for 10 minutes" in box.log()
    assert box.run("auto").returncode == 0 and box.log().count("letting main settle") == 1
    (box.dir / "head").write_text("ccc")
    (box.dir / "landed").write_text(f"{int(time.time()) - 30}\n")
    assert box.run("auto").returncode == 0 and box.running() == "aaa" and "before ccc: it landed 0 min ago" in box.log()
    (box.dir / "landed").write_text(f"{int(time.time()) - 601}\n")
    assert box.run("auto").returncode == 0 and box.running() == "ccc" and box.calls().count("restart") == 1
    (tmp_path / "now").mkdir()
    now = BuiltBox(tmp_path / "now", approved=False)
    (now.dir / "landed").write_text(f"{int(time.time())}\n")
    assert now.run("deploy").returncode == 0 and now.running() == "bbb"
    now.env["DESK_SETTLE"] = "0"
    (now.dir / "head").write_text("ddd")
    assert now.run("auto").returncode == 0 and now.running() == "ddd"
