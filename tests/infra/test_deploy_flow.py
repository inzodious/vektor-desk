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
