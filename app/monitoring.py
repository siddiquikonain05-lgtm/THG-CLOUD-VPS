"""CPU / RAM / disk / job resource monitoring."""
import os
import platform
import time
from pathlib import Path

import psutil

from . import config, process_manager, storage

START = time.time()
psutil.cpu_percent(interval=None)  # prime the counter
_proc_cache = {}


def _read_int(path):
    try:
        v = Path(path).read_text().strip()
        return None if v == "max" else int(v)
    except (OSError, ValueError):
        return None


def memory_info():
    """Prefer the container (cgroup) limit, which is what Railway actually enforces."""
    vm = psutil.virtual_memory()
    used = _read_int("/sys/fs/cgroup/memory.current")
    limit = _read_int("/sys/fs/cgroup/memory.max")
    if used is None:
        used = _read_int("/sys/fs/cgroup/memory/memory.usage_in_bytes")
        limit = _read_int("/sys/fs/cgroup/memory/memory.limit_in_bytes")
    if used is not None:
        limited = limit is not None and limit < 2 ** 60
        total = limit if limited else vm.total
        return {"used": used, "total": total, "percent": round(used / total * 100, 1), "container_limit": limited}
    return {"used": vm.used, "total": vm.total, "percent": vm.percent, "container_limit": False}


def job_usage(pid):
    """CPU% and RSS summed over a job's process tree."""
    try:
        root = _proc_cache.get(pid)
        if root is None or not root.is_running():
            root = _proc_cache[pid] = psutil.Process(pid)
        cpu, rss = 0.0, 0
        for p in [root] + root.children(recursive=True):
            try:
                p = _proc_cache.setdefault(p.pid, p) if p.pid != pid else p
                cpu += p.cpu_percent(interval=None)
                rss += p.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return {"cpu_percent": round(cpu, 1), "memory_rss": rss}
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        _proc_cache.pop(pid, None)
        return {"cpu_percent": None, "memory_rss": None}


def system_status():
    jobs = process_manager.list_jobs()
    running = [j for j in jobs if j["status"] == "RUNNING"]
    try:
        load = os.getloadavg()
    except OSError:
        load = (0, 0, 0)
    return {
        "status": "online",
        "python": platform.python_version(),
        "cpu_percent": psutil.cpu_percent(interval=None),
        "cpu_count": os.cpu_count(),
        "load": load,
        "memory": memory_info(),
        "disk": storage.disk_info(),
        "running_jobs": len(running),
        "total_jobs": len(jobs),
        "workspace": str(config.DATA_DIR),
        "projects_dir": str(config.PROJECTS_DIR),
        "uptime": time.time() - START,
        "recent_jobs": [process_manager.serialize(j) for j in jobs[:5]],
    }
