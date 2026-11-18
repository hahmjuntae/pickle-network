from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import threading
import time
from pathlib import Path

from .paths import read_json, write_json

TOKEN_RE = re.compile(r"pn_([0-9a-f]{8})_([A-Za-z0-9_-]{32,128})")
SCOPES = ("full", "read")
NAME_RE = re.compile(r"[\w.-]{1,40}")
LAST_SEEN_WRITE_INTERVAL = 60


def _digest(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


class Devices:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock = threading.Lock()

    def _load(self) -> list:
        return read_json(self.path, {"devices": []}).get("devices", [])

    def _save(self, devices: list) -> None:
        write_json(self.path, {"devices": devices})

    def create(self, name: str, scope: str = "full") -> tuple:
        if not NAME_RE.fullmatch(name or ""):
            raise ValueError("기기 이름은 영문, 숫자, 한글, 점, 밑줄, 하이픈 40자 이내입니다")
        if scope not in SCOPES:
            raise ValueError("scope는 full 또는 read입니다")
        with self.lock:
            devices = self._load()
            taken = {d["id"] for d in devices}
            device_id = secrets.token_hex(4)
            while device_id in taken:
                device_id = secrets.token_hex(4)
            secret = secrets.token_urlsafe(32)
            record = {"id": device_id, "name": name, "scope": scope, "hash": _digest(secret),
                      "created": time.time(), "last_seen": None, "revoked": None}
            devices.append(record)
            self._save(devices)
        return self.public(record), "pn_%s_%s" % (device_id, secret)

    def verify(self, token: str):
        match = TOKEN_RE.fullmatch(token or "")
        if not match:
            return None
        device_id, secret = match.groups()
        supplied = _digest(secret)
        with self.lock:
            devices = self._load()
            for record in devices:
                if record["id"] != device_id or record.get("revoked"):
                    continue
                if not hmac.compare_digest(record["hash"], supplied):
                    return None
                now = time.time()
                if not record.get("last_seen") or now - record["last_seen"] > LAST_SEEN_WRITE_INTERVAL:
                    record["last_seen"] = now
                    self._save(devices)
                return self.public(record)
        return None

    def list(self) -> list:
        with self.lock:
            return [self.public(d) for d in self._load()]

    def revoke(self, key: str) -> list:
        with self.lock:
            devices = self._load()
            hits = [d for d in devices if not d.get("revoked") and key in (d["id"], d["name"])]
            for record in hits:
                record["revoked"] = time.time()
            if hits:
                self._save(devices)
            return [self.public(d) for d in hits]

    @staticmethod
    def public(record: dict) -> dict:
        return {k: record.get(k) for k in ("id", "name", "scope", "created", "last_seen", "revoked")}
