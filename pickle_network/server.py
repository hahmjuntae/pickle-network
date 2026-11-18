from __future__ import annotations

import json
import logging
import logging.handlers
import os
import platform
import signal
import socket
import socketserver
import threading
import time
import urllib.parse
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import SERVICE, __version__
from .agents import Agents, MODES
from .devices import Devices
from .files import Files
from .guide import guide_text
from .jobs import ApiError, Jobs
from .paths import ensure_home, load_config
from . import shellenv

MAX_BODY = 12 * 1024 * 1024
MAX_WAIT = 90
FAIL_WINDOW = 60
FAIL_LIMIT = 30


class App:
    def __init__(self, root: Path, config: dict):
        self.root = Path(root)
        self.config = config
        self.started = time.time()
        env_record = shellenv.stored()
        self.path_value = env_record["path"]
        self.env_source = env_record.get("source")
        self.devices = Devices(self.root / "devices.json")
        self.files = Files(config["roots"])
        self.agents = Agents(self.path_value)
        self.jobs = Jobs(self.root, config, lambda: shellenv.build_env(self.path_value))
        self.failures = deque()
        self.fail_lock = threading.Lock()
        self.access = logging.getLogger("pickle-network.access")
        if not self.access.handlers:
            handler = logging.handlers.RotatingFileHandler(str(self.root / "logs" / "access.log"),
                                                           maxBytes=1024 * 1024, backupCount=3)
            handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
            self.access.addHandler(handler)
            self.access.setLevel(logging.INFO)
            self.access.propagate = False

    def throttled(self) -> bool:
        now = time.monotonic()
        with self.fail_lock:
            while self.failures and now - self.failures[0] > FAIL_WINDOW:
                self.failures.popleft()
            return len(self.failures) >= FAIL_LIMIT

    def record_failure(self) -> None:
        with self.fail_lock:
            self.failures.append(time.monotonic())

    def hello(self, device: dict) -> dict:
        tunnel = self.config.get("tunnel") or {}
        return {
            "version": __version__,
            "device": device,
            "host": {"name": socket.gethostname().split(".")[0], "os": platform.platform(terse=True),
                     "user": os.environ.get("USER") or Path.home().name, "home": str(Path.home())},
            "public_url": self.config.get("public_url"),
            "tunnel": tunnel.get("mode"),
            "default_cwd": self.config["default_cwd"],
            "file_roots": [str(r) for r in self.files.roots],
            "agents": {name: info.get("version") for name, info in self.agents.detect().items()},
            "agent_modes": {"read": "읽기 위주", "edit": "파일 수정 자동 승인", "full": "모든 도구 자동 승인"},
            "limits": {"default_timeout": self.config["default_timeout"], "max_timeout": self.config["max_timeout"],
                       "max_wait": MAX_WAIT, "concurrency": self.config["concurrency"],
                       "max_file_bytes": 8 * 1024 * 1024, "retention_days": self.config["retention_days"]},
            "endpoints": ["GET /v1/hello", "GET /v1/guide", "GET /v1/health", "POST /v1/run", "POST /v1/ask",
                          "GET /v1/jobs", "GET /v1/jobs/{id}?wait=N", "GET /v1/jobs/{id}/output",
                          "POST /v1/jobs/{id}/cancel", "GET /v1/files?path=", "PUT /v1/files", "GET /v1/client"],
            "sandboxed": False,
        }

    def health(self) -> dict:
        workers = sum(1 for w in self.jobs.workers if w.is_alive())
        return {"status": "ok" if workers else "degraded", "version": __version__,
                "uptime": round(time.time() - self.started, 1), "workers_alive": workers,
                "jobs": self.jobs.counts(), "shell_path_source": self.env_source,
                "access_expires_at": ((self.config.get("tunnel") or {}).get("access") or {}).get("expires_at")}

    def _timeout(self, body: dict) -> int:
        value = body.get("timeout", self.config["default_timeout"])
        if type(value) is not int or not 1 <= value <= int(self.config["max_timeout"]):
            raise ApiError("invalid_timeout", "timeout은 1~%s초 정수입니다" % self.config["max_timeout"])
        return value

    def _cwd(self, body: dict) -> str:
        raw = body.get("cwd") or self.config["default_cwd"]
        if not isinstance(raw, str):
            raise ApiError("invalid_cwd", "cwd는 문자열입니다")
        path = Path(os.path.expanduser(raw))
        if not path.is_absolute() or not path.is_dir():
            raise ApiError("invalid_cwd", "존재하는 절대 폴더가 필요합니다: " + raw)
        return str(path.resolve())

    def run(self, body: dict, device: dict) -> tuple:
        _only(body, {"command", "cwd", "timeout", "wait", "request_id"})
        command = body.get("command")
        if not isinstance(command, str) or not command.strip() or len(command) > 200000:
            raise ApiError("invalid_command", "command 문자열이 필요합니다")
        spec = {"argv": [shellenv.login_shell(), "-lc", command], "cwd": self._cwd(body),
                "timeout": self._timeout(body), "label": command[:200]}
        return self.jobs.submit("run", spec, device["id"], body.get("request_id"))

    def ask(self, body: dict, device: dict) -> tuple:
        _only(body, {"prompt", "agent", "mode", "model", "cwd", "timeout", "wait", "request_id"})
        prompt = body.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 200000:
            raise ApiError("invalid_prompt", "prompt 문자열이 필요합니다")
        mode = body.get("mode", "edit")
        if mode not in MODES:
            raise ApiError("invalid_mode", "mode는 read, edit, full 중 하나입니다")
        model = body.get("model")
        if model is not None and (not isinstance(model, str) or not model or len(model) > 100 or model.startswith("-")):
            raise ApiError("invalid_model", "model 이름이 올바르지 않습니다")
        try:
            agent, argv = self.agents.build(body.get("agent"), prompt, mode, model)
        except LookupError as exc:
            raise ApiError("agent_missing", str(exc), 404)
        except ValueError as exc:
            raise ApiError("invalid_agent", str(exc))
        spec = {"argv": argv, "cwd": self._cwd(body), "timeout": self._timeout(body),
                "label": "%s(%s): %s" % (agent, mode, prompt.strip().splitlines()[0][:160]),
                "agent": agent, "mode": mode, "model": model}
        return self.jobs.submit("ask", spec, device["id"], body.get("request_id"))


def _only(body: dict, allowed: set) -> None:
    if not isinstance(body, dict):
        raise ApiError("invalid_body", "JSON 객체가 필요합니다")
    unknown = set(body) - allowed
    if unknown:
        raise ApiError("invalid_field", "알 수 없는 필드: " + ", ".join(sorted(unknown)))


def _wait_value(raw) -> float:
    try:
        value = float(raw or 0)
    except (TypeError, ValueError):
        raise ApiError("invalid_wait", "wait는 숫자입니다")
    return max(0.0, min(value, float(MAX_WAIT)))


class Handler(BaseHTTPRequestHandler):
    server_version = "pickle-network"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, *unused):
        return

    def _send(self, status: int, value: dict) -> None:
        value = {"ok": status < 400, "service": SERVICE, **value}
        raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(raw)
        self.status_sent = status

    def _body(self) -> dict:
        length = self.headers.get("Content-Length")
        if self.headers.get("Transfer-Encoding"):
            raise ApiError("chunked_unsupported", "Content-Length가 필요합니다", 411)
        try:
            size = int(length or 0)
        except ValueError:
            raise ApiError("invalid_length", "Content-Length가 올바르지 않습니다")
        if size > MAX_BODY:
            self.close_connection = True
            raise ApiError("too_large", "요청 본문이 너무 큽니다", 413)
        raw = self.rfile.read(size) if size else b"{}"
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise ApiError("invalid_json", "JSON 본문이 필요합니다")
        if not isinstance(value, dict):
            raise ApiError("invalid_body", "JSON 객체가 필요합니다")
        return value

    def _route(self, method: str) -> None:
        app = self.server.app
        started = time.monotonic()
        self.status_sent = 0
        route, device = "-", None
        try:
            if self.headers.get("Origin"):
                raise ApiError("browser_denied", "브라우저 페이지에서는 호출할 수 없습니다", 403)
            if app.throttled():
                raise ApiError("too_many_failures", "인증 실패가 많아 잠시 차단했습니다", 429)
            auth = self.headers.get("Authorization", "")
            device = app.devices.verify(auth[7:].strip()) if auth.startswith("Bearer ") else None
            if not device:
                app.record_failure()
                raise ApiError("unauthorized", "유효한 기기 토큰이 필요합니다", 401)
            parsed = urllib.parse.urlsplit(self.path)
            query = dict(urllib.parse.parse_qsl(parsed.query))
            parts = [p for p in parsed.path.split("/") if p]
            route = "/" + "/".join("{id}" if len(p) == 32 else p for p in parts)
            writes = method in ("POST", "PUT")
            if writes and device["scope"] != "full" and route != "/v1/jobs/{id}/cancel":
                raise ApiError("scope_denied", "읽기 전용 기기입니다", 403)
            body = self._body() if writes else {}
            self._dispatch(app, method, route, parts, query, body, device)
        except ApiError as exc:
            self.close_connection = True
            self._send(exc.status, {"error": {"code": exc.code, "message": exc.message}})
        except Exception as exc:
            logging.getLogger("pickle-network").exception("request failed")
            self._send(500, {"error": {"code": "internal_error", "message": type(exc).__name__}})
        finally:
            app.access.info("%s %s %s device=%s %.0fms", method, route, self.status_sent,
                            device["id"] if device else "-", (time.monotonic() - started) * 1000)

    def _dispatch(self, app, method, route, parts, query, body, device) -> None:
        if method == "GET" and route == "/v1/hello":
            return self._send(200, app.hello(device))
        if method == "GET" and route == "/v1/guide":
            return self._send(200, {"guide": guide_text(app.config)})
        if method == "GET" and route == "/v1/health":
            return self._send(200, app.health())
        if method == "GET" and route == "/v1/client":
            source = (Path(__file__).parent / "client.py").read_text("utf-8")
            return self._send(200, {"version": __version__, "source": source})
        if method == "POST" and route in ("/v1/run", "/v1/ask"):
            wait = _wait_value(body.get("wait"))
            job, reused = (app.run if route == "/v1/run" else app.ask)(body, device)
            if wait:
                job = app.jobs.get(job["id"], wait)
            elif job["state"] not in ("queued", "running"):
                job = app.jobs.get(job["id"])
            return self._send(200 if reused else 202, {"job": job, "reused": reused,
                                                       "poll": "/v1/jobs/%s?wait=50" % job["id"]})
        if method == "GET" and route == "/v1/jobs":
            return self._send(200, {"jobs": app.jobs.list(query.get("limit", 20), query.get("state"))})
        if method == "GET" and route == "/v1/jobs/{id}":
            return self._send(200, {"job": app.jobs.get(parts[2], _wait_value(query.get("wait")))})
        if method == "GET" and route == "/v1/jobs/{id}/output":
            return self._send(200, {"output": app.jobs.output(parts[2], query.get("stream", "stdout"),
                                                               query.get("offset", 0), query.get("limit", 65536))})
        if method == "POST" and route == "/v1/jobs/{id}/cancel":
            return self._send(202, app.jobs.cancel(parts[2]))
        if method == "GET" and route == "/v1/files":
            result = app.files.read(query.get("path"), query.get("offset") or 0,
                                    query.get("limit") or 8 * 1024 * 1024)
            return self._send(200, {result["type"]: result})
        if method == "PUT" and route == "/v1/files":
            return self._send(200, {"written": app.files.write(body)})
        raise ApiError("not_found", "없는 API입니다: %s %s" % (method, route), 404)

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")

    def do_PUT(self):
        self._route("PUT")

    def do_DELETE(self):
        self._route("DELETE")


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, app: App):
        self.app = app
        super().__init__(address, Handler)

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name, self.server_port = host, port


def serve(port: int = None) -> None:
    root = ensure_home()
    config = load_config()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    app = App(root, config)
    threading.Thread(target=_refresh_env, args=(app,), daemon=True).start()
    server = Server(("127.0.0.1", int(port or config["port"])), app)

    def stop(*unused):
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    pruner = threading.Thread(target=_prune_loop, args=(app, server), daemon=True)
    pruner.start()
    logging.info("pickle-network %s listening on 127.0.0.1:%s", __version__, server.server_port)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        app.jobs.shutdown()
        server.server_close()
        logging.info("stopped")


def _refresh_env(app: App) -> None:
    record = shellenv.refresh()
    app.path_value, app.env_source = record["path"], record["source"]
    app.agents.path_value = record["path"]
    app.agents.detect(refresh=True)
    logging.info("shell PATH refreshed from %s", record["source"])


def _prune_loop(app: App, server: Server) -> None:
    while True:
        time.sleep(3600)
        try:
            app.jobs.prune()
        except Exception:
            logging.getLogger("pickle-network").exception("prune failed")
