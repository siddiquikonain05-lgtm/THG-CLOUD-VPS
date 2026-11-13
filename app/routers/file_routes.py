import os
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from .. import auth, config, file_manager, storage

router = APIRouter(prefix="/api/files", dependencies=[Depends(auth.require_csrf)])


class PathBody(BaseModel):
    path: str


class RenameBody(BaseModel):
    path: str
    new_name: str


class ExtractBody(BaseModel):
    path: str
    mode: Literal["here", "new_folder"] = "here"


@router.get("/list")
def list_files(path: str = ""):
    return file_manager.list_dir(path)


@router.post("/mkdir")
def mkdir(body: PathBody):
    return {"path": file_manager.make_dir(body.path)}


@router.post("/touch")
def touch(body: PathBody):
    return {"path": file_manager.make_file(body.path)}


@router.post("/rename")
def rename(body: RenameBody):
    return {"path": file_manager.rename(body.path, body.new_name)}


@router.post("/delete")
def delete(body: PathBody):
    file_manager.delete(body.path)
    return {"ok": True}


@router.post("/extract")
def extract(body: ExtractBody):
    return file_manager.extract_zip(body.path, body.mode)


@router.post("/upload")
def upload(path: str = Form(""), relpaths: list[str] = Form(default=[]),
           files: list[UploadFile] = File(...)):
    limit = config.MAX_UPLOAD_MB * 1024 * 1024
    total, saved = 0, []
    for i, f in enumerate(files):
        name = relpaths[i] if i < len(relpaths) and relpaths[i] else (f.filename or "")
        total += file_manager.save_stream(path, name, f.file, limit - total)
        saved.append(name)
    return {"saved": saved, "bytes": total}


@router.get("/download")
def download(path: str):
    p = storage.safe_path(path)
    if p.is_file():
        return FileResponse(p, filename=p.name)
    if p.is_dir():
        tmp = file_manager.zip_dir(p)
        return FileResponse(tmp, filename=p.name + ".zip", media_type="application/zip",
                            background=BackgroundTask(os.unlink, tmp))
    raise file_manager.FileError("Not found")
