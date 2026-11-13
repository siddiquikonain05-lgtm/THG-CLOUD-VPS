import time
import unittest

from app import auth, config, database

try:
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    from app.main import app
    HAVE_API = True
except Exception:  # fastapi/httpx not installed in this environment
    HAVE_API = False

CREDS = {"username": config.TERMINAL_USER, "password": config.TERMINAL_PASSWORD}


class TokenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database.init()

    def test_roundtrip_tamper_expiry_logout(self):
        tok = auth.create_session("tester")
        s = auth.parse_token(tok)
        self.assertEqual(s["u"], "tester")
        self.assertIsNone(auth.parse_token(tok[:-2] + "00"))
        self.assertIsNone(auth.parse_token("garbage"))
        auth.revoke_session(s["sid"])
        self.assertIsNone(auth.parse_token(tok))

    def test_credentials(self):
        self.assertTrue(auth.verify_credentials("tester", "correct-horse-battery"))
        self.assertFalse(auth.verify_credentials("tester", "wrong"))
        self.assertFalse(auth.verify_credentials("other", "correct-horse-battery"))

    def test_rate_limiter(self):
        rl = auth.RateLimiter(3, 60)
        for _ in range(3):
            self.assertFalse(rl.blocked("ip"))
            rl.hit("ip")
        self.assertTrue(rl.blocked("ip"))
        self.assertFalse(rl.blocked("other"))

    def test_startup_refuses_without_credentials(self):
        old = config.SECRET_KEY
        config.SECRET_KEY = "short"
        try:
            with self.assertRaises(RuntimeError):
                config.validate()
        finally:
            config.SECRET_KEY = old

    def test_child_env_hides_secrets(self):
        env = config.shell_env()
        for k in ("TERMINAL_PASSWORD", "SECRET_KEY", "TERMINAL_USER"):
            self.assertNotIn(k, env)


@unittest.skipUnless(HAVE_API, "fastapi / httpx not installed")
class ApiTests(unittest.TestCase):
    def setUp(self):
        self.cm = TestClient(app)
        self.client = self.cm.__enter__()
        auth.login_limiter.hits.clear()

    def tearDown(self):
        self.cm.__exit__(None, None, None)

    def login(self):
        r = self.client.post("/api/auth/login", json=CREDS)
        self.assertEqual(r.status_code, 200)
        self.assertIn("httponly", r.headers["set-cookie"].lower())
        self.assertIn("samesite=strict", r.headers["set-cookie"].lower())
        return self.client.get("/api/auth/me").json()["csrf"]

    def test_invalid_password_rejected(self):
        r = self.client.post("/api/auth/login", json={**CREDS, "password": "nope-nope"})
        self.assertEqual(r.status_code, 401)

    def test_login_rate_limited(self):
        for _ in range(5):
            self.client.post("/api/auth/login", json={**CREDS, "password": "nope-nope"})
        self.assertEqual(self.client.post("/api/auth/login", json=CREDS).status_code, 429)

    def test_all_api_routes_require_auth(self):
        for method, url in [("get", "/api/files/list"), ("get", "/api/files/download?path=projects"),
                            ("post", "/api/files/mkdir"), ("post", "/api/files/delete"),
                            ("post", "/api/files/upload"), ("post", "/api/files/extract"),
                            ("get", "/api/jobs"), ("post", "/api/jobs"), ("post", "/api/jobs/1/stop"),
                            ("get", "/api/jobs/1/log"), ("get", "/api/system/status"),
                            ("get", "/api/system/storage"), ("post", "/api/system/cleanup"),
                            ("get", "/api/terminal/sessions")]:
            r = getattr(self.client, method)(url)
            self.assertEqual(r.status_code, 401, f"{method} {url}")
        self.assertEqual(self.client.get("/", follow_redirects=False).status_code, 307)

    def test_websocket_requires_auth(self):
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect("/ws/terminal") as ws:
                ws.receive_text()

    def test_csrf_enforced(self):
        csrf = self.login()
        self.assertEqual(self.client.post("/api/files/mkdir", json={"path": "projects/c1"}).status_code, 403)
        r = self.client.post("/api/files/mkdir", json={"path": "projects/c1"}, headers={"X-CSRF-Token": csrf})
        self.assertEqual(r.status_code, 200)

    def test_logout_revokes_session(self):
        csrf = self.login()
        self.client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf})
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_upload_and_job_flow(self):
        csrf = self.login()
        h = {"X-CSRF-Token": csrf}
        r = self.client.post("/api/files/upload", headers=h, data={"path": "projects", "relpaths": ["up/app.py"]},
                             files=[("files", ("app.py", b"print('hi from upload')\n"))])
        self.assertEqual(r.status_code, 200, r.text)
        job = self.client.post("/api/jobs", headers=h, json={"command": "python3 app.py", "cwd": "projects/up"}).json()
        for _ in range(50):
            job = self.client.get(f"/api/jobs/{job['id']}").json()
            if job["status"] != "RUNNING":
                break
            time.sleep(0.1)
        self.assertEqual(job["status"], "COMPLETED")
        log = self.client.get(f"/api/jobs/{job['id']}/log?stream=stdout").json()
        self.assertIn("hi from upload", log["data"])

    def test_terminal_executes_commands(self):
        self.login()
        with self.client.websocket_connect("/ws/terminal?cols=100&rows=30") as ws:
            self.assertEqual(ws.receive_json()["type"], "session")
            ws.send_text('{"type":"input","data":"echo THG$((20+22))\\n"}')
            seen = b""
            for _ in range(60):
                seen += ws.receive_bytes()
                if b"THG42" in seen.replace(b"echo THG$((20+22))", b""):
                    break
            self.assertIn(b"THG42", seen)


if __name__ == "__main__":
    unittest.main()
