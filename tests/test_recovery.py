"""Session recovery across reboot / long idle (boot-id based)."""

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness import autopilot, bg_jobs, system_identity


def test_boot_id_stable_and_nonempty():
    a = system_identity.boot_id()
    assert a and isinstance(a, str)
    assert system_identity.boot_id() == a            # cached / stable


def test_rebooted_since_logic():
    assert system_identity.rebooted_since(None) is True
    assert system_identity.rebooted_since("unknown-boot") is True
    assert system_identity.rebooted_since("some-old-boot") is True
    assert system_identity.rebooted_since(system_identity.boot_id()) is False


def test_human_gap():
    assert system_identity.human_gap(10) == "10s"
    assert system_identity.human_gap(300) == "5m"
    assert system_identity.human_gap(7200) == "2h"
    assert system_identity.human_gap(200000) == "2d"


def test_bg_job_marked_ended_after_simulated_reboot():
    with tempfile.TemporaryDirectory() as d:
        job = bg_jobs.start('python3 -c "__import__(\'time\').sleep(30)"', d)
        assert job.status == "running" and bg_jobs._alive(job.pid)
        # simulate a reboot: rewrite the stored boot_id to a stale value
        reg = Path(d) / "bg_jobs.json"
        recs = json.loads(reg.read_text())
        for r in recs:
            r["boot_id"] = "linux:STALE-BOOT-FROM-YESTERDAY"
        reg.write_text(json.dumps(recs))
        # even though the PID is still alive, reboot wins → ended
        listed = bg_jobs.list_jobs(d)
        rec = next(r for r in listed if r["id"] == job.id)
        assert rec["status"] == "ended"
        assert any("reboot" in x for x in rec.get("reasons", []))
        bg_jobs.stop(d, job.id)                       # clean up the process


def test_cowork_resume_after_reboot_and_day():
    with tempfile.TemporaryDirectory() as d:
        s = autopilot.start("keep the build healthy", d)
        autopilot.run(s, cycles=3)
        step = s.state["step"]
        # simulate: a day passed AND the machine rebooted
        s.state["last_active"] = time.time() - 26 * 3600
        s.state["boot_id"] = "linux:STALE-BOOT"
        s.save()

        # it shows up as recoverable, flagged rebooted
        rec = autopilot.recoverable(d)
        assert any(r["session"] == s.sid and r["rebooted"] for r in rec)

        fresh = autopilot.load(d, s.sid)              # like a new CLI call
        entries = autopilot.resume(fresh, cycles=2)
        assert fresh.state["step"] == step + 2
        rec_entry = next(e for e in fresh.read_journal()
                         if e["type"] == "recovery")
        assert rec_entry["rebooted"] is True
        assert rec_entry["idle_seconds"] >= 24 * 3600


def test_stopped_session_not_recoverable():
    with tempfile.TemporaryDirectory() as d:
        s = autopilot.start("done thing", d)
        autopilot.stop(s)
        assert all(r["session"] != s.sid
                   for r in autopilot.recoverable(d))


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    p = 0
    for fn in fns:
        try:
            fn(); p += 1; print("PASS", fn.__name__)
        except Exception:
            print("FAIL", fn.__name__); traceback.print_exc()
    print(f"{p}/{len(fns)} passed")
