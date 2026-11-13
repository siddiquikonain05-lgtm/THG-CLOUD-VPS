"""File operations on the workspace, with traversal / zip-slip protection."""
import os
import re
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path

from . import config
from .storage import rel_path, safe_path


class FileError(ValueError):
    pass


_PROTECTED = {config.DATA_DIR / n for n in ("projects", "uploads", "logs", "system", "database")}
_READONLY_TREES = (config.DATA_DIR / "system", config.DATA_DIR / "database")


def _check_writable(p):
    if p == config.DATA_DIR or p in _PROTECTED:
        raise FileError("This is a protected top-level folder")
    for tree in _READONLY_TREES:
        if p == tree or p.is_relative_to(tree):
            raise FileError("system/ and database/ are managed by the app and read-only here")


def _check_parent_writable(p):
    for tree in _READONLY_TREES:
        if p == tree or p.is_relative_to(tree):
            raise FileError("system/ and database/ are managed by the app and read-only here")


def _clean_name(name):
    name = (name or "").strip()
    if not name or name in (".", "..") or "/" in name or "\\" in name or "\x00" in name:
        raise FileError("Invalid name")
    if len(name) > 255:
        raise FileError("Name too long")
    return name


def list_dir(rel):
    p = safe_path(rel)
    if not p.is_dir():
        raise FileError("Folder not found")
    items = []
    for e in os.scandir(p):
        try:
            st = e.stat()
            is_dir = e.is_dir()
        except OSError:
            continue
        items.append({"name": e.name, "path": rel_path(p / e.name), "is_dir": is_dir,
                      "size": None if is_dir else st.st_size, "mtime": st.st_mtime,
                      "is_zip": (not is_dir) and e.name.lower().endswith(".zip")})
    items.sort(key=lambda i: (not i["is_dir"], i["name"].lower()))
    return {"path": rel_path(p), "parent": None if p == config.DATA_DIR else rel_path(p.parent),
            "items": items}


def make_dir(rel):
    p = safe_path(rel)
    _check_parent_writable(p)
    if p.exists():
        raise FileError("Already exists")
    _clean_name(p.name)
    p.mkdir(parents=True)
    return rel_path(p)


def make_file(rel):
    p = safe_path(rel)
    _check_parent_writable(p)
    if p.exists():
        raise FileError("Already exists")
    _clean_name(p.name)
    if not p.parent.is_dir():
        raise FileError("Parent folder does not exist")
    p.touch()
    return rel_path(p)


def rename(rel, new_name):
    p = safe_path(rel)
    _check_writable(p)
    if not p.exists() and not p.is_symlink():
        raise FileError("Not found")
    target = p.with_name(_clean_name(new_name))
    if target.exists():
        raise FileError("A file or folder with that name already exists")
    os.rename(p, target)
    return rel_path(target)


def delete(rel):
    p = safe_path(rel)
    _check_writable(p)
    if not p.exists():
        raise FileError("Not found")
    if p.is_dir() and not p.is_symlink():
        shutil.rmtree(p)
    else:
        p.unlink()


def save_stream(dest_rel, relname, src, max_bytes):
    """Stream an uploaded file to disk, keeping any sub-folders in relname."""
    dest = safe_path(dest_rel)
    _check_parent_writable(dest)
    if not dest.is_dir():
        raise FileError("Destination folder not found")
    parts = [x for x in (relname or "").replace("\\", "/").split("/") if x not in ("", ".")]
    if not parts or ".." in parts or "\x00" in relname:
        raise FileError(f"Unsafe file name: {relname!r}")
    target = dest.joinpath(*parts)
    resolved = target.parent.resolve() / target.name
    if not resolved.is_relative_to(config.DATA_DIR):
        raise FileError("Upload path escapes the workspace")
    free = shutil.disk_usage(config.DATA_DIR).free
    if free < 20 * 1024 * 1024:
        raise FileError("Disk is almost full")
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.parent / f".{target.name}.part"
    written = 0
    try:
        with open(tmp, "wb") as out:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise FileError(f"Upload exceeds the {config.MAX_UPLOAD_MB} MB limit")
                out.write(chunk)
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)
    return written


def zip_dir(p):
    """Zip a folder into a temp file under system/tmp; caller deletes it."""
    fd, tmp = tempfile.mkstemp(suffix=".zip", dir=config.TMP_DIR)
    os.close(fd)
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        zf.write(p, p.name + "/")
        for root, dirs, files in os.walk(p, followlinks=False):
            for d in dirs:
                full = Path(root) / d
                if not full.is_symlink():
                    zf.write(full, (Path(p.name) / full.relative_to(p)).as_posix() + "/")
            for f in files:
                full = Path(root) / f
                if full.is_symlink():
                    continue
                zf.write(full, (Path(p.name) / full.relative_to(p)).as_posix())
    return tmp


_DRIVE = re.compile(r"^[A-Za-z]:")


def _entry_parts(info):
    name = info.filename.replace("\\", "/")
    if name.startswith("/") or _DRIVE.match(name) or "\x00" in name:
        raise FileError(f"Unsafe entry in archive: {info.filename!r}")
    parts = [x for x in name.split("/") if x not in ("", ".")]
    if ".." in parts:
        raise FileError(f"Unsafe entry in archive: {info.filename!r}")
    return parts


def extract_zip(rel, mode="here"):
    zpath = safe_path(rel)
    if not zpath.is_file() or not zipfile.is_zipfile(zpath):
        raise FileError("Not a valid ZIP file")
    if mode == "new_folder":
        dest = zpath.parent / zpath.stem
        n = 1
        while dest.exists():
            n += 1
            dest = zpath.parent / f"{zpath.stem}-{n}"
    elif mode == "here":
        dest = zpath.parent
    else:
        raise FileError("mode must be 'here' or 'new_folder'")
    _check_parent_writable(dest)
    limit = config.MAX_EXTRACT_MB * 1024 * 1024
    created_dest = not dest.exists()
    created, count, total = [], 0, 0
    with zipfile.ZipFile(zpath) as zf:
        infos = zf.infolist()
        if len(infos) > config.MAX_EXTRACT_FILES:
            raise FileError("Archive contains too many entries")
        plan = []
        for info in infos:  # validate everything BEFORE writing anything
            parts = _entry_parts(info)
            if not parts or parts[0] == "__MACOSX":
                continue
            if info.flag_bits & 0x1:
                raise FileError("Encrypted archives are not supported")
            mode_bits = info.external_attr >> 16
            if stat.S_ISLNK(mode_bits):
                raise FileError(f"Archive contains a symbolic link: {info.filename!r}")
            total += info.file_size
            if total > limit:
                raise FileError(f"Archive expands beyond the {config.MAX_EXTRACT_MB} MB limit")
            plan.append((info, parts, mode_bits))
        if shutil.disk_usage(config.DATA_DIR).free < total + 20 * 1024 * 1024:
            raise FileError("Not enough free disk space to extract")
        dest.mkdir(parents=True, exist_ok=True)
        root = dest.resolve()
        written_total = 0
        try:
            for info, parts, mode_bits in plan:
                target = root.joinpath(*parts)
                if not (target.parent.resolve() / target.name).is_relative_to(root):
                    raise FileError(f"Unsafe entry in archive: {info.filename!r}")
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as out:
                    created.append(target)
                    while True:
                        chunk = src.read(1024 * 1024)
                        if not chunk:
                            break
                        written_total += len(chunk)
                        if written_total > limit:  # don't trust declared sizes
                            raise FileError("Archive expands beyond the size limit")
                        out.write(chunk)
                os.chmod(target, 0o755 if mode_bits & 0o100 else 0o644)
                count += 1
        except Exception:
            for f in created:
                f.unlink(missing_ok=True)
            if created_dest:
                shutil.rmtree(dest, ignore_errors=True)
            raise
    return {"extracted_to": rel_path(dest), "files": count}
