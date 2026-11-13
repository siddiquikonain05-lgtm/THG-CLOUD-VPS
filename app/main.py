"""THG CLOUD VPS - private web terminal, file manager and background job runner."""
import asyncio
import os
import signal
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import auth, config, database, file_manager, process_manager, storage, terminal
from .routers import file_routes, log_routes, process_routes, system_routes, terminal_routes


async def _maintenance():
    ticks = 0
    while True:
        await asyncio.sleep(30)
        ticks += 1
        try:
            await asyncio.to_thread(process_manager.reconcile)
            if ticks % 10 == 0:
                await asyncio.to_thread(storage.rotate_logs)
                await asyncio.to_thread(storage.purge_tmp)
                await asyncio.to_thread(auth.purge_sessions)
        except Exception as exc:  # never let maintenance kill the server
            print("maintenance error:", exc, flush=True)


def _graceful_job_shutdown():
    """Container is going down: ask jobs to exit cleanly. They are reported INTERRUPTED next boot."""
    for job in database.query("SELECT * FROM jobs WHERE status='RUNNING'"):
        if process_manager._is_alive(job):
            try:
                os.killpg(job["pid"], signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
    time.sleep(2)


@asynccontextmanager
async def lifespan(_app):
    config.validate()
    storage.ensure_layout()
    database.init()
    process_manager.reconcile()
    storage.rotate_logs()
    task = asyncio.create_task(_maintenance())
    yield
    task.cancel()
    terminal.registry.shutdown()
    await asyncio.to_thread(_graceful_job_shutdown)


app = FastAPI(title="THG CLOUD VPS", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.exception_handler(ValueError)
async def value_error_handler(_request, exc):  # FileError, PathError, JobError ...
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.middleware("http")
async def guards(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/"):
        if not auth.api_limiter.allow(auth.client_ip(request)):
            return JSONResponse({"detail": "Rate limit exceeded"}, status_code=429)
        if path == "/api/files/upload":
            try:
                size = int(request.headers.get("content-length", "0"))
            except ValueError:
                size = 0
            if size > (config.MAX_UPLOAD_MB + 8) * 1024 * 1024:
                return JSONResponse({"detail": f"Request larger than {config.MAX_UPLOAD_MB} MB limit"},
                                    status_code=413)
    response = await call_next(request)
    response.headers.update({
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Cache-Control": "no-store" if path.startswith("/api/") or path in ("/", "/login") else "no-cache",
        "Content-Security-Policy": (
            "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data:; "
            "connect-src 'self' ws: wss:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"),
    })
    return response


for r in (auth.router, file_routes.router, process_routes.router, log_routes.router,
          system_routes.router, terminal_routes.api, terminal_routes.router):
    app.include_router(r)

app.mount("/css", StaticFiles(directory=config.FRONTEND_DIR / "css"), name="css")
app.mount("/js", StaticFiles(directory=config.FRONTEND_DIR / "js"), name="js")


def _logged_in(request):
    return auth.parse_token(request.cookies.get(auth.COOKIE, "")) is not None


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"ok": True}


@app.get("/login", include_in_schema=False)
def login_page(request: Request):
    if _logged_in(request):
        return RedirectResponse("/")
    return FileResponse(config.FRONTEND_DIR / "login.html")


@app.get("/", include_in_schema=False)
def index(request: Request):
    if not _logged_in(request):
        return RedirectResponse("/login")
    return FileResponse(config.FRONTEND_DIR / "index.html")
