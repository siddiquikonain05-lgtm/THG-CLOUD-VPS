# THG CLOUD VPS

A **private**, single-user web terminal, file manager and background-job runner for Railway.
Real Linux shell (PTY + WebSockets + xterm.js), Python 3.12, persistent files and logs on a Railway Volume.
No Firebase, Supabase or external database: everything lives under `/data`.

> **Personal use only.** This gives a logged-in user a shell inside the container. Keep your password long and secret.

## What "persistent" really means here

| Thing | Survives browser close | Survives container restart / redeploy |
|---|---|---|
| Running scripts (background jobs) | **Yes** | **No** – live processes cannot survive a restart |
| Interactive shell (and what runs in it) | **Yes** (reattach later) | **No** |
| Files, projects, logs, job history, pip packages | Yes | **Yes** (on the `/data` volume) |

After a restart, jobs that were running are shown honestly as **INTERRUPTED** (never falsely "RUNNING"). Use **Restart** to start them again from the stored command + directory. Each redeploy restarts the container. No keep-alive pings are used; the app does not try to bypass any Railway sleep policy.

## Deploy: GitHub → Railway

1. **GitHub:** create a *private* repo, then from this folder:
   ```bash
   git init && git add . && git commit -m "THG CLOUD VPS"
   git branch -M main
   git remote add origin https://github.com/<you>/<repo>.git
   git push -u origin main
   ```
   (Or use "Add file → Upload files" in the GitHub web UI.) `.env` is git-ignored; never commit real credentials.
2. **Railway:** New Project → *Deploy from GitHub repo* → pick the repo. `railway.json` makes it build with the `Dockerfile`.
3. **Variables** (service → Variables):
   | Name | Value |
   |---|---|
   | `TERMINAL_USER` | your username |
   | `TERMINAL_PASSWORD` | long password (≥ 8 chars required) |
   | `SECRET_KEY` | `python -c "import secrets; print(secrets.token_urlsafe(48))"` (≥ 16 chars required) |
   | `DATA_DIR` | `/data` |
   `PORT` is set by Railway. The app **refuses to start** if the credentials are missing or too short.
4. **Volume:** service → *Settings → Volumes (or ⌘K "Volume") → Add volume* → mount path **`/data`**.
5. **Domain:** *Settings → Networking → Generate Domain*. Open the URL.
6. **First login:** sign in with `TERMINAL_USER` / `TERMINAL_PASSWORD`. Open **Terminal** and run `ls` → you'll see `another-project  my-project`.

Keep it at one replica (a volume can only attach to one instance). Compute and volume storage are billed/limited by your Railway plan – check Railway's current pricing and limits.

## Using it

**Upload `app.py`, `holo.txt`, `requirements.txt`:** *Files → open `projects/my-project` → Upload files.* They replace the empty placeholders. Folders: *Upload folder* keeps the directory structure.

**Upload and extract a ZIP:** upload `my-project.zip` into `projects/my-project`, then on its row choose **Extract Here**, **Extract to New Folder**, or **Delete ZIP**. Extraction rejects `..` paths, absolute paths, symlinks, encrypted archives, too many entries and zip bombs (limit `MAX_EXTRACT_MB`), and writes nothing if validation fails.

**Run a script (interactive):**
```bash
cd my-project
pip install -r requirements.txt     # goes into a venv on /data → survives redeploys
python app.py
```
`Ctrl+C` stops it (on mobile use the key bar: `^C`, `Tab`, arrows, sticky `Ctrl`). The shell itself keeps running if you close the tab – reopen **Terminal** and you reattach with the output replayed (last 512 KB).

**Run a script in the background (recommended for long jobs):**
- Web: *Processes → command `python app.py`, directory `/data/projects/my-project` → Run in background*
- Terminal: `thgjob run python app.py` (runs in your current folder), then `thgjob list`, `thgjob logs 3 -f`, `thgjob logs 3 --err`, `thgjob stop 3`, `thgjob restart 3`, `thgjob rm 3`

Background jobs run in their own process group, log straight to `/data/logs/job-<id>.stdout.log` / `.stderr.log`, and don't depend on any browser, WebSocket or terminal. Close everything, come back hours later: **Processes** shows ID, PID, status, runtime, exit code, CPU/RAM, and **Logs** shows live + historical output.

**Manage processes:** *Processes* → **View output**, **Stop** (SIGINT → SIGTERM → SIGKILL on the whole group, after verifying PID + start time), **Restart** (always a *new* job), **Delete history** (finished jobs only).

**Logs page:** stdout and stderr in separate panes, incremental polling (never loads whole files), auto-reconnect, *Pause scrolling*, *Clear screen* (display only, logs stay), *Load earlier*, *Download*. Timestamps shown are the log file's last-write time when the chunk was fetched (jobs write directly to files, so per-line timestamps aren't added).

## Storage & safety

- Everything important is in `/data`: `projects/ uploads/ logs/ system/ database/` (+ `system/venv`, `system/home` for pip packages and shell history). `system/` and `database/` are read-only in the file manager; top-level folders can't be deleted there.
- Logs of a job that grows beyond `MAX_LOG_MB` are rotated (copy-truncate, `LOG_KEEP` files; a few bytes written during the copy can be lost). Nothing else is deleted automatically. *Settings → Storage* offers a preview-then-confirm cleanup of old finished-job logs. A banner warns at `DISK_WARN_PERCENT` disk usage.
- Auth: signed `HttpOnly` + `SameSite=Strict` (+ `Secure` on HTTPS) cookie backed by a server-side session table (real logout/revocation), CSRF header on every unsafe request, Origin check, login limiter (5 failures / 5 min / IP), global API limiter, WebSocket auth + Origin check, constant-time credential comparison.
- Shell and jobs run as an unprivileged user (uid 1000) with `no-new-privs`; the container is not privileged and mounts no Docker socket. `TERMINAL_PASSWORD`, `SECRET_KEY`, `TERMINAL_USER` and `PORT` are removed from the environment of everything you run. You can still consume the container's CPU/RAM/disk with arbitrary code.
- There is no `sudo`/root in the shell, so `apt install` is unavailable; use pip, or add packages to the `Dockerfile`.
- Browser assets `xterm.js` / `xterm-addon-fit` load from the jsDelivr CDN (pinned versions).

## Local run (optional)
```bash
pip install -r requirements-dev.txt
export TERMINAL_USER=me TERMINAL_PASSWORD=long-password SECRET_KEY=$(python -c "import secrets;print(secrets.token_urlsafe(48))") DATA_DIR=$PWD/data
mkdir -p data && python -m uvicorn app.main:app --port 8000
```
Tests: `python -m unittest discover -s tests -t .` (or `pytest`).

## Environment variables
`TERMINAL_USER`, `TERMINAL_PASSWORD`, `SECRET_KEY`, `DATA_DIR`, `PORT` (required/standard) · optional: `SESSION_HOURS` (72), `MAX_UPLOAD_MB` (512), `MAX_EXTRACT_MB` (2048), `MAX_EXTRACT_FILES` (50000), `MAX_LOG_MB` (50), `LOG_KEEP` (3), `MAX_TERMINALS` (5), `MAX_RUNNING_JOBS` (20), `DISK_WARN_PERCENT` (85).
