"""Workspace layout, safe paths, disk usage, log rotation and cleanup tools."""
import os
import shutil
import time
from pathlib import Path

from . import config, database


class PathError(ValueError):
    pass


BASHRC = r"""# THG CLOUD VPS shell settings (edit freely; this file is only created once)
PS1='\[\e[1;32m\]thg\[\e[0m\]@\[\e[1;36m\]cloud\[\e[0m\]:\[\e[1;34m\]\w\[\e[0m\]\$ '
HISTFILE="$HOME/.bash_history"
HISTSIZE=5000
HISTFILESIZE=20000
shopt -s histappend
PROMPT_COMMAND='history -a'
alias ls='ls --color=auto'
alias ll='ls -lah'
alias job='thgjob'
"""


def ensure_layout():
    for d in (config.PROJECTS_DIR, config.UPLOADS_DIR, config.LOGS_DIR, config.SYSTEM_DIR,
              config.DATABASE_DIR, config.HOME_DIR, config.TMP_DIR, config.EXIT_DIR):
        d.mkdir(parents=True, exist_ok=True)
    marker = config.SYSTEM_DIR / ".seeded"
    if not marker.exists():  # sample projects are created only on the very first start
        proj = config.PROJECTS_DIR / "my-project"
        (proj / "output").mkdir(parents=True, exist_ok=True)
        for name in ("app.py", "holo.txt", "requirements.txt"):
            (proj / name).touch(exist_ok=True)
        (config.PROJECTS_DIR / "another-project").mkdir(exist_ok=True)
        marker.write_text("seeded\n")
    rc = config.HOME_DIR / ".bashrc"
    if not rc.exists():
        rc.write_text(BASHRC)


def safe_path(rel):
    """Resolve a workspace-relative path; refuse anything that escapes DATA_DIR."""
    rel = (rel or "").replace("\\", "/")
    if "\x00" in rel:
        raise PathError("Invalid path")
    p = (config.DATA_DIR / rel.lstrip("/")).resolve()
    if p != config.DATA_DIR and not p.is_relative_to(config.DATA_DIR):
        raise PathError("Path escapes the workspace")
    return p


def rel_path(p):
    p = Path(p)
    return "" if p == config.DATA_DIR else p.relative_to(config.DATA_DIR).as_posix()


def disk_info():
    u = shutil.disk_usage(config.DATA_DIR)
    pct = round(u.used / u.total * 100, 1) if u.total else 0.0
    return {"total": u.total, "used": u.used, "free": u.free, "percent": pct,
            "warning": pct >= config.DISK_WARN_PERCENT,
            "warn_percent": config.DISK_WARN_PERCENT}


def dir_size(path):
    total = 0
    for root, _dirs, files in os.walk(path, followlinks=False):
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total


def storage_report():
    sizes = {}
    for name in ("projects", "uploads", "logs", "system", "database"):
        d = config.DATA_DIR / name
        sizes[name] = dir_size(d) if d.exists() else 0
    return {"disk": disk_info(), "sizes": sizes, "max_upload_mb": config.MAX_UPLOAD_MB,
            "max_extract_mb": config.MAX_EXTRACT_MB, "max_log_mb": config.MAX_LOG_MB}


def rotate_log(path):
    """copy-truncate rotation; keeps LOG_KEEP rotated files (path.1 is newest)."""
    keep = max(1, config.LOG_KEEP)
    for i in range(keep, 1, -1):
        src = path.with_name(f"{path.name}.{i - 1}")
        if src.exists():
            os.replace(src, path.with_name(f"{path.name}.{i}"))
    shutil.copyfile(path, path.with_name(f"{path.name}.1"))
    with open(path, "r+b") as f:  # writers use O_APPEND, so they continue at the new end
        f.truncate(0)


def rotate_logs(limit_bytes=None):
    limit = limit_bytes if limit_bytes is not None else config.MAX_LOG_MB * 1024 * 1024
    rotated = []
    for p in config.LOGS_DIR.glob("job-*.log"):
        try:
            if p.stat().st_size > limit:
                rotate_log(p)
                rotated.append(p.name)
        except OSError:
            pass
    return rotated


def cleanup_logs(older_than_days, dry_run=True):
    """Delete log files of FINISHED jobs older than N days. Only runs when asked."""
    cutoff = time.time() - float(older_than_days) * 86400
    rows = database.query(
        "SELECT id FROM jobs WHERE status != 'RUNNING' AND ended_at IS NOT NULL AND ended_at < ?",
        (cutoff,))
    files, total = [], 0
    for r in rows:
        for p in config.LOGS_DIR.glob(f"job-{r['id']}.*"):
            try:
                size = p.stat().st_size
            except OSError:
                continue
            files.append({"name": p.name, "size": size})
            total += size
            if not dry_run:
                p.unlink(missing_ok=True)
    return {"files": files, "bytes": total, "deleted": not dry_run}


def purge_tmp(max_age_seconds=3600):
    """Remove our own stale temp archives (never user data)."""
    now = time.time()
    for p in config.TMP_DIR.glob("*"):
        try:
            if p.is_file() and now - p.stat().st_mtime > max_age_seconds:
                p.unlink()
        except OSError:
            pass
