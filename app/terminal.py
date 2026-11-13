"""Persistent interactive PTY shells.

A shell lives in the server, not in the WebSocket: if the browser disconnects the
shell (and anything running in it) keeps going, output keeps being buffered, and a
new WebSocket can re-attach and replay the buffer.
"""
import fcntl
import os
import pty
import signal
import struct
import subprocess
import termios
import threading
import time
import uuid

from . import config

BUFFER_LIMIT = 512 * 1024


class TerminalError(RuntimeError):
    pass


class TerminalSession:
    def __init__(self, loop, cols=80, rows=24):
        self.id = uuid.uuid4().hex[:12]
        self.loop = loop
        self.created = time.time()
        self.buffer = bytearray()
        self.subscribers = set()
        self.alive = True
        master, slave = pty.openpty()
        self._winsize(master, cols, rows)

        def _preexec():  # make the PTY the controlling terminal (after setsid)
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)

        try:
            self.proc = subprocess.Popen(
                ["/bin/bash"], stdin=slave, stdout=slave, stderr=slave,
                cwd=str(config.PROJECTS_DIR), env=config.shell_env(),
                start_new_session=True, preexec_fn=_preexec, close_fds=True)
        finally:
            os.close(slave)
        self.master = master
        os.set_blocking(master, False)
        loop.add_reader(master, self._on_readable)

    @staticmethod
    def _winsize(fd, cols, rows):
        cols = max(2, min(int(cols), 500))
        rows = max(2, min(int(rows), 200))
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def _on_readable(self):
        try:
            data = os.read(self.master, 65536)
        except BlockingIOError:
            return
        except OSError:
            data = b""
        if not data:
            self._close()
            return
        self.buffer += data
        if len(self.buffer) > BUFFER_LIMIT:
            del self.buffer[:len(self.buffer) - BUFFER_LIMIT]
        for q in list(self.subscribers):
            q.put_nowait(data)

    def _close(self):
        if not self.alive:
            return
        self.alive = False
        try:
            self.loop.remove_reader(self.master)
        except Exception:
            pass
        try:
            os.close(self.master)
        except OSError:
            pass
        threading.Thread(target=self.proc.wait, daemon=True).start()  # reap
        for q in list(self.subscribers):
            q.put_nowait(None)

    def write(self, data):
        view = memoryview(data)
        while view and self.alive:
            try:
                n = os.write(self.master, view)
                view = view[n:]
            except BlockingIOError:
                time.sleep(0.005)
            except OSError:
                break

    def resize(self, cols, rows):
        if self.alive:
            try:
                self._winsize(self.master, cols, rows)
            except OSError:
                pass

    def kill(self):
        if not self.alive:
            return
        try:
            os.killpg(self.proc.pid, signal.SIGHUP)
        except (ProcessLookupError, PermissionError):
            pass
        self.loop.call_later(2.0, self._force_kill)

    def _force_kill(self):
        if self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        self._close()

    def subscribe(self):
        import asyncio
        q = asyncio.Queue()
        self.subscribers.add(q)
        return q, bytes(self.buffer)

    def unsubscribe(self, q):
        self.subscribers.discard(q)

    def info(self):
        return {"id": self.id, "created": self.created, "alive": self.alive,
                "clients": len(self.subscribers)}


class Registry:
    def __init__(self):
        self.sessions = {}

    def _prune(self):
        for sid in [s for s, t in self.sessions.items() if not t.alive and not t.subscribers]:
            del self.sessions[sid]

    def get(self, sid):
        s = self.sessions.get(sid)
        return s if s and s.alive else None

    def create(self, loop, cols=80, rows=24):
        self._prune()
        if sum(1 for s in self.sessions.values() if s.alive) >= config.MAX_TERMINALS:
            raise TerminalError(f"Too many open terminals (limit {config.MAX_TERMINALS}). "
                                "Close one from the session list.")
        s = TerminalSession(loop, cols, rows)
        self.sessions[s.id] = s
        return s

    def list(self):
        self._prune()
        return [s.info() for s in self.sessions.values() if s.alive]

    def kill(self, sid):
        s = self.sessions.get(sid)
        if not s:
            return False
        s.kill()
        return True

    def shutdown(self):
        for s in list(self.sessions.values()):
            if s.alive:
                try:
                    os.killpg(s.proc.pid, signal.SIGHUP)
                except (ProcessLookupError, PermissionError):
                    pass


registry = Registry()
