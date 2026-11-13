import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

from app import config, database, process_manager as pm, storage

ROOT = Path(__file__).resolve().parent.parent


def wait_for(job_id, statuses, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        job = pm.refresh_job(pm.get_job(job_id))
        if job["status"] in statuses:
            return job
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} stuck in {job['status']}")


class ProcessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        storage.ensure_layout()
        database.init()

    def test_completed_with_logs(self):
        j = pm.start_job("echo out-line; echo err-line 1>&2")
        j = wait_for(j["id"], {"COMPLETED", "FAILED"})
        self.assertEqual(j["status"], "COMPLETED")
        self.assertEqual(j["exit_code"], 0)
        self.assertIn("out-line", pm.read_log(j["id"], "stdout")["data"])
        self.assertIn("err-line", pm.read_log(j["id"], "stderr")["data"])

    def test_failed_exit_code(self):
        j = wait_for(pm.start_job("exit 3")["id"], {"FAILED", "COMPLETED"})
        self.assertEqual((j["status"], j["exit_code"]), ("FAILED", 3))

    def test_stop_marks_stopped_and_kills_group(self):
        j = pm.start_job("sleep 300 & sleep 300")
        self.assertEqual(j["status"], "RUNNING")
        j = pm.stop_job(j["id"])
        self.assertEqual(j["status"], "STOPPED")
        self.assertFalse(pm._is_alive({"pid": j["pid"], "pid_start": j["pid_start"]}))

    def test_restart_creates_new_job(self):
        first = wait_for(pm.start_job("echo again")["id"], {"COMPLETED"})
        second = pm.restart_job(first["id"])
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(second["restart_of"], first["id"])
        self.assertEqual(second["command"], first["command"])
        wait_for(second["id"], {"COMPLETED"})

    def test_stale_pid_is_interrupted_not_running(self):
        jid = database.execute(
            "INSERT INTO jobs (name,command,cwd,pid,pid_start,status,started_at) VALUES (?,?,?,?,?,?,?)",
            ("ghost", "sleep 1", str(config.PROJECTS_DIR), 999999, 12345, "RUNNING", time.time()))
        pm.reconcile()
        self.assertEqual(pm.get_job(jid)["status"], "INTERRUPTED")

    def test_pid_reuse_is_detected(self):
        # our own PID is alive, but with a different start time it is NOT the same process
        jid = database.execute(
            "INSERT INTO jobs (name,command,cwd,pid,pid_start,status,started_at) VALUES (?,?,?,?,?,?,?)",
            ("reuse", "x", str(config.PROJECTS_DIR), os.getpid(), 1, "RUNNING", time.time()))
        pm.reconcile()
        self.assertEqual(pm.get_job(jid)["status"], "INTERRUPTED")

    def test_cli_job_survives_without_server(self):
        """`thgjob run` exits immediately; the job must keep running and finish on its own."""
        env = dict(os.environ, THG_APP_ROOT=str(ROOT))
        out = subprocess.run([sys.executable, str(ROOT / "scripts/thgjob"), "run", "--",
                              "sh", "-c", "sleep 1; echo survived"],
                             capture_output=True, text=True, env=env, check=True,
                             cwd=str(config.PROJECTS_DIR)).stdout
        jid = int(out.split()[2])
        self.assertEqual(pm.refresh_job(pm.get_job(jid))["status"], "RUNNING")
        j = wait_for(jid, {"COMPLETED"})
        self.assertIn("survived", pm.read_log(jid, "stdout")["data"])
        self.assertEqual(j["exit_code"], 0)

    def test_relative_cwd_is_workspace_relative(self):
        (config.PROJECTS_DIR / "up").mkdir(exist_ok=True)
        j = wait_for(pm.start_job("pwd", "projects/up")["id"], {"COMPLETED"})
        self.assertEqual(j["cwd"], str(config.PROJECTS_DIR / "up"))
        self.assertIn("projects/up", pm.read_log(j["id"], "stdout")["data"])

    def test_bad_cwd_rejected_and_delete_history(self):
        with self.assertRaises(pm.JobError):
            pm.start_job("echo x", "/etc")
        j = wait_for(pm.start_job("echo bye")["id"], {"COMPLETED"})
        pm.delete_job(j["id"])
        self.assertIsNone(pm.get_job(j["id"]))
        self.assertFalse(pm.log_path(j["id"], "stdout").exists())

    def test_log_rotation_and_offsets(self):
        j = wait_for(pm.start_job("python3 -c \"print('x'*5000)\"")["id"], {"COMPLETED"})
        path = pm.log_path(j["id"], "stdout")
        storage.rotate_logs(limit_bytes=1000)
        self.assertEqual(path.stat().st_size, 0)
        self.assertTrue(path.with_name(path.name + ".1").exists())
        r = pm.read_log(j["id"], "stdout", offset=5000)  # stale offset after rotation
        self.assertTrue(r["reset"])


if __name__ == "__main__":
    unittest.main()
