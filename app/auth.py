"""Private authentication: signed session cookie + server-side session store + CSRF."""
import base64
import hashlib
import hmac
import json
import secrets
import time
from collections import defaultdict, deque
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, Response, WebSocket
from pydantic import BaseModel

from . import config, database

COOKIE = "thg_session"


class RateLimiter:
    """Sliding-window limiter, in memory (fine for a single private instance)."""

    def __init__(self, max_hits, window):
        self.max_hits, self.window = max_hits, window
        self.hits = defaultdict(deque)

    def _trim(self, key):
        q, now = self.hits[key], time.monotonic()
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    def blocked(self, key):
        return len(self._trim(key)) >= self.max_hits

    def hit(self, key):
        self._trim(key).append(time.monotonic())

    def allow(self, key):
        if self.blocked(key):
            return False
        self.hit(key)
        return True

    def reset(self, key):
        self.hits.pop(key, None)


login_limiter = RateLimiter(5, 300)  # 5 failed logins / 5 min / IP
api_limiter = RateLimiter(300, 10)  # 300 API calls / 10 s / IP


def _sign(raw):
    return hmac.new(config.SECRET_KEY.encode(), raw.encode(), hashlib.sha256).hexdigest()


def create_session(user):
    sid, csrf = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    exp = int(time.time() + config.SESSION_HOURS * 3600)
    database.execute("INSERT INTO sessions (sid, expires) VALUES (?,?)", (sid, exp))
    raw = base64.urlsafe_b64encode(json.dumps({"u": user, "sid": sid, "exp": exp, "csrf": csrf}).encode()).decode()
    return raw + "." + _sign(raw)


def parse_token(token):
    try:
        raw, sig = token.rsplit(".", 1)
        if not hmac.compare_digest(sig, _sign(raw)):
            return None
        data = json.loads(base64.urlsafe_b64decode(raw.encode()))
        if data["exp"] < time.time():
            return None
        if not database.query("SELECT 1 FROM sessions WHERE sid=? AND expires>?", (data["sid"], time.time())):
            return None  # logged out / revoked
        return data
    except Exception:
        return None


def revoke_session(sid):
    database.execute("DELETE FROM sessions WHERE sid=?", (sid,))


def purge_sessions():
    database.execute("DELETE FROM sessions WHERE expires<?", (time.time(),))


def verify_credentials(user, password):
    """Constant-time comparison of both fields (hashed first so lengths don't leak)."""
    h = lambda s: hashlib.sha256(s.encode()).digest()
    ok_user = hmac.compare_digest(h(user), h(config.TERMINAL_USER))
    ok_pass = hmac.compare_digest(h(password), h(config.TERMINAL_PASSWORD))
    return ok_user and ok_pass


def client_ip(request):
    return request.client.host if request.client else "unknown"


def same_origin(headers):
    origin = headers.get("origin")
    if not origin:
        return True  # non-browser clients; browsers always send Origin on POST/WebSocket
    return urlparse(origin).netloc == headers.get("host", "")


def current_session(request: Request):
    s = parse_token(request.cookies.get(COOKIE, ""))
    if not s:
        raise HTTPException(401, "Not authenticated")
    return s


def require_csrf(request: Request, s=Depends(current_session)):
    """Dependency for every API router: must be logged in; unsafe methods need the CSRF header."""
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        if not hmac.compare_digest(request.headers.get("x-csrf-token", ""), s["csrf"]):
            raise HTTPException(403, "Missing or invalid CSRF token")
        if not same_origin(request.headers):
            raise HTTPException(403, "Cross-origin request refused")
    return s


def ws_authorized(ws: WebSocket):
    return bool(parse_token(ws.cookies.get(COOKIE, ""))) and same_origin(ws.headers)


class LoginBody(BaseModel):
    username: str
    password: str


router = APIRouter(prefix="/api/auth")


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response):
    ip = client_ip(request)
    if not same_origin(request.headers):
        raise HTTPException(403, "Cross-origin request refused")
    if login_limiter.blocked(ip):
        raise HTTPException(429, "Too many failed attempts. Try again in a few minutes.")
    if not verify_credentials(body.username, body.password):
        login_limiter.hit(ip)
        time.sleep(0.5)
        raise HTTPException(401, "Invalid username or password")
    login_limiter.reset(ip)
    token = create_session(config.TERMINAL_USER)
    response.set_cookie(COOKIE, token, max_age=config.SESSION_HOURS * 3600, httponly=True,
                        samesite="strict", secure=request.url.scheme == "https", path="/")
    return {"ok": True}


@router.post("/logout")
def logout(response: Response, s=Depends(require_csrf)):
    revoke_session(s["sid"])
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(s=Depends(current_session)):
    return {"user": s["u"], "csrf": s["csrf"]}
