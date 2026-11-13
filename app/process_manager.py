"""Detached background job supervisor.

Jobs are started in their own session/process group, write straight to log files
and never depend on a browser, a WebSocket or even this server staying up.
Identity of a job is (pid, process start time) so PID reuse cannot fool us.
Only the stdlib is used so the `thgjob` CLI can import this module.
"""
import os
import shlex
import signal
import subprocess
import threading
import time
from pathlib import Path

from . import config, database


class JobError(ValueError):
    pass


def log_path(job_id, stream):
    return config.LOGS_DIR / f"job-{job_id}.{stream}.log"


def exit_path(job_id):
    return config.EXIT_DIR / f"job-{job_id}.exit"


def _proc_start(pid):
    """Start time (clock ticks since boot) of a live process, else None (gone/zombie)."""
    try:
        with open(f"/proc/{int(pid)}/stat", "rb") as f:
            data = f.read().decode("utf-8", "replace")
    except (OSError, ValueError, TypeError):
        return None
    rest = data[data.rindex(")") + 2:].split()
    if rest[0] in ("Z", "X"):
        return None
    return int(rest[19])  # field 22 of /proc/<pid>/stat


def _is_alive(job):
    if not job.get("pid") or job.get("pid_start") is None:
        return False
    return _proc_start(job["pid"]) == job["pid_start"]


def get_job(job_id):
    rows = database.query("SELECT * FROM jobs WHERE id=?", (int(job_id),))
    return rows[0] if rows else None


def refresh_job(job):
    """Re-evaluate a RUNNING job against reality and persist the outcome."""
    if job is None or job["status"] != "RUNNING" or _is_alive(job):
        return job
    code, ended = None, time.time()
    p = exit_path(job["id"])
    try:
        code = int(p.read_text().strip())
        ended = p.stat().st_mtime
    except (OSError, ValueError):
        pass
    if job["stop_requested"]:
        status = "STOPPED"
    elif code is None:
        status = "INTERRUPTED"  # process vanished without reporting: container/server restart or kill
    elif code == 0:
        status = "COMPLETED"
    else:
        status = "FAILED"
    database.execute(
        "UPDATE jobs SET status=?, exit_code=?, ended_at=? WHERE id=? AND status='RUNNING'",
        (status, code, ended, job["id"]))
    return get_job(job["id"])


def list_jobs(limit=None):
    sql = "SELECT * FROM jobs ORDER BY id DESC"
    args = ()
    if limit:
        sql += " LIMIT ?"
        args = (int(limit),)
    return [refresh_job(j) for j in database.query(sql, args)]


def reconcile():
    """Run at startup: mark jobs whose process no longer exists (never lie about RUNNING)."""
    for j in database.query("SELECT * FROM jobs WHERE status='RUNNING'"):
        refresh_job(j)


def _resolve_cwd(cwd):
    p = Path(cwd) if cwd else config.PROJECTS_DIR
    if not p.is_absolute():  # relative paths are workspace-relative, like the file manager ("projects/up")
        p = config.DATA_DIR / p
    p = p.resolve()
    if not (p == config.DATA_DIR or p.is_relative_to(config.DATA_DIR)) or not p.is_dir():
        raise JobError("Working directory must be an existing folder inside the workspace")
    return p


def _script_name(command):
    try:
        parts = shlex.split(command)
    except ValueError:
        parts = command.split()
    for part in parts:
        if part.endswith(".py"):
            return os.path.basename(part)
    return os.path.basename(parts[0]) if parts else command[:30]


def start_job(command, cwd=None, restart_of=None, reap=True):
    command = (command or "").strip()
    if not command:
        raise JobError("Command is empty")
    if len(command) > 4000:
        raise JobError("Command is too long")
    workdir = _resolve_cwd(cwd)
    running = database.query("SELECT COUNT(*) AS n FROM jobs WHERE status='RUNNING'")[0]["n"]
    if running >= config.MAX_RUNNING_JOBS:
        raise JobError(f"Too many running jobs (limit {config.MAX_RUNNING_JOBS})")
    config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    config.EXIT_DIR.mkdir(parents=True, exist_ok=True)
    job_id = database.execute(
        "INSERT INTO jobs (name, command, cwd, status, started_at, restart_of) "
        "VALUES (?,?,?,?,?,?)",
        (_script_name(command), command, str(workdir), "RUNNING", time.time(), restart_of))
    exit_path(job_id).unlink(missing_ok=True)
    out = open(log_path(job_id, "stdout"), "ab")
    err = open(log_path(job_id, "stderr"), "ab")
    try:
        # Outer bash records the exit code of the inner command in a file, so the
        # result survives even if this server restarts while the job runs.
        proc = subprocess.Popen(
            ["/bin/bash", "-c", 'bash -c "$1"; echo $? > "$2"', "thg-job", command,
             str(exit_path(job_id))],
            cwd=str(workdir), stdin=subprocess.DEVNULL, stdout=out, stderr=err,
            env=config.shell_env(), start_new_session=True, close_fds=True)
    except OSError as exc:
        database.execute("UPDATE jobs SET status='FAILED', exit_code=127, ended_at=? WHERE id=?",
                         (time.time(), job_id))
        raise JobError(f"Could not start job: {exc}") from exc
    finally:
        out.close()
        err.close()
    database.execute("UPDATE jobs SET pid=?, pid_start=? WHERE id=?",
                     (proc.pid, _proc_start(proc.pid), job_id))
    if reap:
        def _reap():
            proc.wait()
            refresh_job(get_job(job_id))
        threading.Thread(target=_reap, daemon=True, name=f"reap-{job_id}").start()
    return refresh_job(get_job(job_id))


def stop_job(job_id, grace=5.0):
    """SIGINT -> SIGTERM -> SIGKILL on the job's process group, verifying identity first."""
    job = refresh_job(get_job(job_id))
    if job is None:
        raise JobError("Job not found")
    if job["status"] != "RUNNING":
        return job
    database.execute("UPDATE jobs SET stop_requested=1 WHERE id=?", (job["id"],))
    job["stop_requested"] = 1
    for sig, wait in ((signal.SIGINT, grace), (signal.SIGTERM, grace), (signal.SIGKILL, 3.0)):
        if not _is_alive(job):
            break
        try:
            os.killpg(job["pid"], sig)
        except ProcessLookupError:
            break
        except PermissionError as exc:
            raise JobError(f"Not allowed to signal job: {exc}") from exc
        deadline = time.time() + wait
        while time.time() < deadline and _is_alive(job):
            time.sleep(0.1)
    return refresh_job(get_job(job_id))


def restart_job(job_id):
    """Start a NEW job from the stored command + cwd (dead processes are never resurrected)."""
    job = get_job(job_id)
    if job is None:
        raise JobError("Job not found")
    if refresh_job(job)["status"] == "RUNNING":
        stop_job(job_id)
    return start_job(job["command"], job["cwd"], restart_of=job["id"])


def delete_job(job_id):
    job = refresh_job(get_job(job_id))
    if job is None:
        raise JobError("Job not found")
    if job["status"] == "RUNNING":
        raise JobError("Stop the job before deleting its history")
    database.execute("DELETE FROM jobs WHERE id=?", (job["id"],))
    for p in config.LOGS_DIR.glob(f"job-{job['id']}.*"):
        p.unlink(missing_ok=True)
    exit_path(job["id"]).unlink(missing_ok=True)


def read_log(job_id, stream="stdout", offset=-1, limit=65536):
    """Incremental log read. offset=-1 returns the tail. Never loads the whole file."""
    if stream not in ("stdout", "stderr"):
        raise JobError("stream must be stdout or stderr")
    limit = max(1, min(int(limit), 1024 * 1024))
    path = log_path(job_id, stream)
    try:
        st = path.stat()
    except OSError:
        return {"data": "", "offset": 0, "next_offset": 0, "size": 0, "mtime": None, "reset": False}
    size, reset = st.st_size, False
    if offset < 0:
        offset = max(0, size - limit)
    elif offset > size:  # file was rotated/truncated
        offset, reset = 0, True
    with open(path, "rb") as f:
        f.seek(offset)
        raw = f.read(limit)
    return {"data": raw.decode("utf-8", "replace"), "offset": offset,
            "next_offset": offset + len(raw), "size": size, "mtime": st.st_mtime, "reset": reset}


def _size(p):
    try:
        return p.stat().st_size
    except OSError:
        return 0


def serialize(job):
    end = job["ended_at"] or time.time()
    j = dict(job)
    j["runtime"] = max(0.0, end - job["started_at"])
    j["stop_requested"] = bool(job["stop_requested"])
    j["stdout_size"] = _size(log_path(job["id"], "stdout"))
    j["stderr_size"] = _size(log_path(job["id"], "stderr"))
    return j
