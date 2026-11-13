from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, monitoring, process_manager as pm

router = APIRouter(prefix="/api/jobs", dependencies=[Depends(auth.require_csrf)])


class StartBody(BaseModel):
    command: str
    cwd: Optional[str] = None


def _full(job):
    j = pm.serialize(job)
    usage = monitoring.job_usage(job["pid"]) if job["status"] == "RUNNING" else {}
    j.update({"cpu_percent": None, "memory_rss": None, **usage})
    return j


def _need(job_id):
    job = pm.refresh_job(pm.get_job(job_id))
    if job is None:
        raise HTTPException(404, "Job not found")
    return job


@router.get("")
def list_jobs(limit: int = 100):
    return [_full(j) for j in pm.list_jobs(limit)]


@router.post("")
def start(body: StartBody):
    return _full(pm.start_job(body.command, body.cwd))


@router.get("/{job_id}")
def get(job_id: int):
    return _full(_need(job_id))


@router.post("/{job_id}/stop")
def stop(job_id: int):
    _need(job_id)
    return _full(pm.stop_job(job_id))


@router.post("/{job_id}/restart")
def restart(job_id: int):
    _need(job_id)
    return _full(pm.restart_job(job_id))


@router.delete("/{job_id}")
def delete(job_id: int):
    _need(job_id)
    pm.delete_job(job_id)
    return {"ok": True}
