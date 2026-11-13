from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from .. import auth, process_manager as pm

router = APIRouter(prefix="/api/jobs/{job_id}/log", dependencies=[Depends(auth.require_csrf)])


@router.get("")
def read(job_id: int, stream: str = "stdout", offset: int = -1, limit: int = 65536):
    if pm.get_job(job_id) is None:
        raise HTTPException(404, "Job not found")
    return pm.read_log(job_id, stream, offset, limit)


@router.get("/download")
def download(job_id: int, stream: str = "stdout"):
    if stream not in ("stdout", "stderr") or pm.get_job(job_id) is None:
        raise HTTPException(404, "Log not found")
    path = pm.log_path(job_id, stream)
    if not path.exists():
        raise HTTPException(404, "Log not found")
    return FileResponse(path, filename=path.name, media_type="text/plain")
