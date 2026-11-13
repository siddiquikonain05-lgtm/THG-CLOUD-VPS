"""Central configuration, read from environment variables."""
import os
from pathlib import Path


def _int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


DATA_DIR = Path(os.environ.get("DATA_DIR", "/data")).resolve()
PORT = _int("PORT", 8000)
TERMINAL_USER = os.environ.get("TERMINAL_USER", "")
TERMINAL_PASSWORD = os.environ.get("TERMINAL_PASSWORD", "")
SECRET_KEY = os.environ.get("SECRET_KEY", "")

SESSION_HOURS = _int("SESSION_HOURS", 72)
MAX_UPLOAD_MB = _int("MAX_UPLOAD_MB", 512)
MAX_EXTRACT_MB = _int("MAX_EXTRACT_MB", 2048)
MAX_EXTRACT_FILES = _int("MAX_EXTRACT_FILES", 50000)
MAX_LOG_MB = _int("MAX_LOG_MB", 50)
LOG_KEEP = _int("LOG_KEEP", 3)
MAX_TERMINALS = _int("MAX_TERMINALS", 5)
MAX_RUNNING_JOBS = _int("MAX_RUNNING_JOBS", 20)
DISK_WARN_PERCENT = _int("DISK_WARN_PERCENT", 85)

PROJECTS_DIR = DATA_DIR / "projects"
UPLOADS_DIR = DATA_DIR / "uploads"
LOGS_DIR = DATA_DIR / "logs"
SYSTEM_DIR = DATA_DIR / "system"
DATABASE_DIR = DATA_DIR / "database"
HOME_DIR = SYSTEM_DIR / "home"
VENV_DIR = SYSTEM_DIR / "venv"
TMP_DIR = SYSTEM_DIR / "tmp"
EXIT_DIR = SYSTEM_DIR / "exit"
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

# Never leak these into the shells / jobs the user runs.
_HIDDEN_ENV = ("TERMINAL_USER", "TERMINAL_PASSWORD", "SECRET_KEY", "PORT")


def validate():
    """Refuse to start without private credentials (no default public access)."""
    problems = []
    if not TERMINAL_USER:
        problems.append("TERMINAL_USER is not set")
    if len(TERMINAL_PASSWORD) < 8:
        problems.append("TERMINAL_PASSWORD must be set and at least 8 characters")
    if len(SECRET_KEY) < 16:
        problems.append("SECRET_KEY must be set and at least 16 characters")
    if problems:
        raise RuntimeError("Refusing to start: " + "; ".join(problems))


def shell_env():
    """Environment for terminal shells and background jobs (secrets removed)."""
    env = {k: v for k, v in os.environ.items() if k not in _HIDDEN_ENV}
    venv_bin = str(VENV_DIR / "bin")
    path = env.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    if venv_bin not in path.split(":"):
        path = venv_bin + ":" + path
    env.update(PATH=path, HOME=str(HOME_DIR), VIRTUAL_ENV=str(VENV_DIR),
               PYTHONUNBUFFERED="1", TERM="xterm-256color",
               LANG="C.UTF-8", LC_ALL="C.UTF-8")
    env.pop("PYTHONHOME", None)
    return env
