from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import select
import shutil
import signal
import sqlite3
import subprocess
import threading
import time
import uuid
from pathlib import Path

INLINE_BYTES = 64 * 1024
TERMINAL_STATES = ("succeeded", "failed", "timed_out", "canceled", "interrupted", "error")
REQUEST_ID_RE = re.compile(r"[A-Za-z0-9._:-]{1,100}")
JOB_ID_RE = re.compile(r"[0-9a-f]{32}")
STREAMS = ("stdout", "stderr")


class ApiError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class Pump(threading.Thread):
    def __init__(self, stream, path: Path, cap: int):
        super().__init__(daemon=True)
        self.fd = stream.fileno()
        self.stream = stream
        self.path = path
        self.cap = cap
        self.total = 0
        self.written = 0
        self.halt = threading.Event()

    def run(self) -> None:
        with open(self.path, "ab") as sink:
            while not self.halt.is_set():
                ready, _, _ = select.select([self.fd], [], [], 0.2)
                if not ready:
                    continue
                try:
                    chunk = os.read(self.fd, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                self.total += len(chunk)
                room = self.cap - self.written
                if room > 0:
                    sink.write(chunk[:room])
                    sink.flush()
                    self.written += min(room, len(chunk))
        self.stream.close()


class Jobs:
    def __init__(self, root: Path, config: dict, env_factory):
        self.root = Path(root)
        self.config = config
        self.env_factory = env_factory
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(self.root / "jobs.sqlite3"), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, request_id TEXT UNIQUE, "
            "fingerprint TEXT NOT NULL, device TEXT, kind TEXT NOT NULL, spec TEXT NOT NULL, "
            "state TEXT NOT NULL, created REAL NOT NULL, started REAL, finished REAL, pid INTEGER, "
            "exit_code INTEGER, error TEXT, stdout_bytes INTEGER DEFAULT 0, "
            "stderr_bytes INTEGER DEFAULT 0, truncated INTEGER DEFAULT 0)")
        self.db.execute("CREATE INDEX IF NOT EXISTS jobs_state ON jobs(state, created)")
        with self.db:
            for row in self.db.execute("SELECT id, pid, state FROM jobs WHERE state IN ('queued','running')").fetchall():
                note = "서버가 다시 시작돼 작업 추적이 끊겼습니다"
                if row["state"] == "running" and row["pid"]:
                    note += ". 프로세스 그룹 %d이 남아 있을 수 있습니다" % row["pid"]
                self.db.execute("UPDATE jobs SET state='interrupted', finished=?, error=? WHERE id=?",
                                (time.time(), canonical({"code": "server_restarted", "message": note}), row["id"]))
        self.prune()
        self.queue = queue.Queue()
        self.cancels = {}
        self.done = {}
        self.stopping = threading.Event()
        self.workers = [threading.Thread(target=self._work, name="pn-worker-%d" % i, daemon=True)
                        for i in range(max(1, int(config.get("concurrency", 3))))]
        for worker in self.workers:
            worker.start()

    def submit(self, kind: str, spec: dict, device: str, request_id: str = None) -> tuple:
        if request_id is not None and not REQUEST_ID_RE.fullmatch(str(request_id)):
            raise ApiError("invalid_request_id", "request_id는 영문, 숫자, ._:- 100자 이내입니다")
        fingerprint = hashlib.sha256(canonical({"kind": kind, "spec": spec}).encode()).hexdigest()
        with self.lock, self.db:
            if request_id:
                row = self.db.execute("SELECT * FROM jobs WHERE request_id=?", (request_id,)).fetchone()
                if row:
                    if row["fingerprint"] != fingerprint:
                        raise ApiError("request_id_conflict", "같은 request_id로 다른 작업을 보냈습니다", 409)
                    return self.public(row), True
            queued = self.db.execute("SELECT count(*) FROM jobs WHERE state='queued'").fetchone()[0]
            if queued >= int(self.config.get("max_queued", 100)):
                raise ApiError("queue_full", "대기 작업이 너무 많습니다. 잠시 뒤 다시 시도하세요", 429)
            job_id = uuid.uuid4().hex
            self.db.execute("INSERT INTO jobs (id, request_id, fingerprint, device, kind, spec, state, created) "
                            "VALUES (?,?,?,?,?,?,?,?)",
                            (job_id, request_id, fingerprint, device, kind, canonical(spec), "queued", time.time()))
            self.cancels[job_id] = threading.Event()
            self.done[job_id] = threading.Event()
            row = self.db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        self.queue.put(job_id)
        return self.public(row), False

    def _row(self, job_id: str):
        if not JOB_ID_RE.fullmatch(job_id or ""):
            raise ApiError("not_found", "작업이 없습니다", 404)
        with self.lock:
            row = self.db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise ApiError("not_found", "작업이 없습니다", 404)
        return row

    def get(self, job_id: str, wait: float = 0) -> dict:
        row = self._row(job_id)
        if wait > 0 and row["state"] not in TERMINAL_STATES:
            event = self.done.get(job_id)
            if event:
                event.wait(wait)
            row = self._row(job_id)
        return self.public(row, inline=True)

    def list(self, limit: int = 20, state: str = None) -> list:
        limit = max(1, min(int(limit), 200))
        with self.lock:
            if state:
                rows = self.db.execute("SELECT * FROM jobs WHERE state=? ORDER BY created DESC LIMIT ?",
                                       (state, limit)).fetchall()
            else:
                rows = self.db.execute("SELECT * FROM jobs ORDER BY created DESC LIMIT ?", (limit,)).fetchall()
        return [self.public(row) for row in rows]

    def counts(self) -> dict:
        with self.lock:
            rows = self.db.execute("SELECT state, count(*) AS n FROM jobs GROUP BY state").fetchall()
        return {row["state"]: row["n"] for row in rows}

    def output(self, job_id: str, stream: str, offset: int, limit: int) -> dict:
        row = self._row(job_id)
        if stream not in STREAMS:
            raise ApiError("invalid_stream", "stream은 stdout 또는 stderr입니다")
        limit = max(1, min(int(limit), 1024 * 1024))
        offset = max(0, int(offset))
        path = self.root / "jobs" / job_id / stream
        size = path.stat().st_size if path.exists() else 0
        data = b""
        if offset < size:
            with open(path, "rb") as source:
                source.seek(offset)
                data = source.read(limit)
        return {"job_id": job_id, "stream": stream, "state": row["state"], "offset": offset,
                "next_offset": offset + len(data), "stored_bytes": size,
                "eof": offset + len(data) >= size and row["state"] in TERMINAL_STATES,
                "text": data.decode("utf-8", "replace")}

    def cancel(self, job_id: str) -> dict:
        row = self._row(job_id)
        if row["state"] in TERMINAL_STATES:
            return {"job": self.public(row), "canceled": False, "reason": "already_finished"}
        event = self.cancels.get(job_id)
        if event:
            event.set()
        with self.lock, self.db:
            self.db.execute("UPDATE jobs SET state='canceled', finished=?, error=? WHERE id=? AND state='queued'",
                            (time.time(), canonical({"code": "canceled", "message": "실행 전에 취소했습니다"}), job_id))
        if self._row(job_id)["state"] == "canceled":
            self._finish_event(job_id)
        return {"job": self.public(self._row(job_id)), "canceled": True}

    def shutdown(self) -> None:
        self.stopping.set()
        for event in list(self.cancels.values()):
            event.set()
        for worker in self.workers:
            worker.join(timeout=8)

    def prune(self) -> int:
        cutoff = time.time() - float(self.config.get("retention_days", 14)) * 86400
        with self.lock, self.db:
            rows = self.db.execute("SELECT id FROM jobs WHERE finished IS NOT NULL AND finished < ?", (cutoff,)).fetchall()
            for row in rows:
                shutil.rmtree(self.root / "jobs" / row["id"], ignore_errors=True)
                self.db.execute("DELETE FROM jobs WHERE id=?", (row["id"],))
        return len(rows)

    def public(self, row, inline: bool = False) -> dict:
        spec = json.loads(row["spec"])
        finished = row["finished"]
        value = {
            "id": row["id"], "request_id": row["request_id"], "kind": row["kind"], "label": spec.get("label"),
            "agent": spec.get("agent"), "cwd": spec.get("cwd"), "state": row["state"],
            "exit_code": row["exit_code"], "created": row["created"], "started": row["started"],
            "finished": finished, "device": row["device"],
            "duration": round((finished or time.time()) - row["started"], 3) if row["started"] else None,
            "stdout_bytes": row["stdout_bytes"], "stderr_bytes": row["stderr_bytes"],
            "output_truncated": bool(row["truncated"]),
            "error": json.loads(row["error"]) if row["error"] else None,
        }
        if inline:
            for stream in STREAMS:
                path = self.root / "jobs" / row["id"] / stream
                size = path.stat().st_size if path.exists() else 0
                with (open(path, "rb") if size else _empty()) as source:
                    if size > INLINE_BYTES:
                        source.seek(size - INLINE_BYTES)
                    data = source.read(INLINE_BYTES)
                value[stream] = data.decode("utf-8", "replace")
                value[stream + "_complete"] = size <= INLINE_BYTES and not row["truncated"]
            if not (value["stdout_complete"] and value["stderr_complete"]):
                value["more_output"] = "/v1/jobs/%s/output?stream=stdout&offset=0" % row["id"]
        return value

    def _finish_event(self, job_id: str) -> None:
        event = self.done.pop(job_id, None)
        self.cancels.pop(job_id, None)
        if event:
            event.set()

    def _work(self) -> None:
        while not self.stopping.is_set():
            try:
                job_id = self.queue.get(timeout=0.3)
            except queue.Empty:
                continue
            try:
                self._run(job_id)
            except Exception as exc:
                with self.lock, self.db:
                    self.db.execute("UPDATE jobs SET state='error', finished=?, error=? WHERE id=? AND state NOT IN %s"
                                    % str(TERMINAL_STATES),
                                    (time.time(), canonical({"code": "internal_error", "message": type(exc).__name__}), job_id))
            finally:
                self._finish_event(job_id)

    def _run(self, job_id: str) -> None:
        with self.lock, self.db:
            row = self.db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None or row["state"] != "queued":
                return
            self.db.execute("UPDATE jobs SET state='running', started=? WHERE id=?", (time.time(), job_id))
        spec = json.loads(row["spec"])
        cancel = self.cancels.get(job_id) or threading.Event()
        folder = self.root / "jobs" / job_id
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            proc = subprocess.Popen(spec["argv"], cwd=spec["cwd"], env=self.env_factory(),
                                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, start_new_session=True)
        except OSError as exc:
            self._complete(job_id, "error", None, {"code": "spawn_failed", "message": exc.strerror or str(exc)}, 0, 0, False)
            return
        with self.lock, self.db:
            self.db.execute("UPDATE jobs SET pid=? WHERE id=?", (proc.pid, job_id))
        cap = int(self.config.get("max_output_bytes", 16 * 1024 * 1024))
        pumps = [Pump(proc.stdout, folder / "stdout", cap), Pump(proc.stderr, folder / "stderr", cap)]
        for pump in pumps:
            pump.start()
        deadline = time.monotonic() + float(spec["timeout"])
        reason = None
        while True:
            try:
                proc.wait(timeout=0.25)
                break
            except subprocess.TimeoutExpired:
                pass
            if cancel.is_set():
                reason = "interrupted" if self.stopping.is_set() else "canceled"
                break
            if time.monotonic() >= deadline:
                reason = "timed_out"
                break
            self._sync_counts(job_id, pumps)
        if reason:
            _stop_group(proc)
        for pump in pumps:
            pump.join(timeout=3)
            pump.halt.set()
        for pump in pumps:
            pump.join(timeout=2)
        truncated = any(p.total > p.written for p in pumps)
        if reason == "timed_out":
            state, error = "timed_out", {"code": "timed_out", "message": "제한 시간 %s초를 넘겨 중단했습니다" % spec["timeout"]}
        elif reason == "canceled":
            state, error = "canceled", {"code": "canceled", "message": "요청에 따라 프로세스 그룹을 중단했습니다"}
        elif reason == "interrupted":
            state, error = "interrupted", {"code": "server_stopping", "message": "서버 종료로 중단했습니다"}
        elif proc.returncode == 0:
            state, error = "succeeded", None
        else:
            state, error = "failed", {"code": "nonzero_exit", "message": "종료 코드 %s" % proc.returncode}
        self._complete(job_id, state, proc.returncode, error, pumps[0].total, pumps[1].total, truncated)

    def _sync_counts(self, job_id: str, pumps: list) -> None:
        with self.lock, self.db:
            self.db.execute("UPDATE jobs SET stdout_bytes=?, stderr_bytes=? WHERE id=?",
                            (pumps[0].total, pumps[1].total, job_id))

    def _complete(self, job_id, state, exit_code, error, out_bytes, err_bytes, truncated) -> None:
        with self.lock, self.db:
            self.db.execute("UPDATE jobs SET state=?, exit_code=?, error=?, finished=?, stdout_bytes=?, "
                            "stderr_bytes=?, truncated=? WHERE id=?",
                            (state, exit_code, canonical(error) if error else None, time.time(),
                             out_bytes, err_bytes, int(truncated), job_id))


class _empty:
    def __enter__(self):
        return self

    def __exit__(self, *unused):
        return False

    def read(self, *unused):
        return b""

    def seek(self, *unused):
        return 0


def _stop_group(proc) -> None:
    for sig, grace in ((signal.SIGTERM, 3.0), (signal.SIGKILL, 3.0)):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            return
        except PermissionError:
            if proc.poll() is None:
                proc.send_signal(sig)
        try:
            proc.wait(timeout=grace)
            if sig == signal.SIGTERM:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
            return
        except subprocess.TimeoutExpired:
            continue
