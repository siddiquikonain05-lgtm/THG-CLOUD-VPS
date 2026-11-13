from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from .. import auth, config, monitoring, storage

router = APIRouter(prefix="/api/system", dependencies=[Depends(auth.require_csrf)])


class CleanupBody(BaseModel):
    older_than_days: float = Field(30, ge=0)
    dry_run: bool = True


@router.get("/status")
def status():
    return monitoring.system_status()


@router.get("/storage")
def storage_report():
    return storage.storage_report()


@router.post("/cleanup")
def cleanup(body: CleanupBody):
    """Deletes logs of finished jobs older than N days, only when dry_run is false."""
    return storage.cleanup_logs(body.older_than_days, body.dry_run)


@router.get("/info")
def info():
    return {"workspace": str(config.DATA_DIR), "max_upload_mb": config.MAX_UPLOAD_MB,
            "max_extract_mb": config.MAX_EXTRACT_MB, "max_log_mb": config.MAX_LOG_MB,
            "log_keep": config.LOG_KEEP, "session_hours": config.SESSION_HOURS,
            "max_running_jobs": config.MAX_RUNNING_JOBS}
