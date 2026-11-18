from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

DEFAULT_PORT = 7979


def home() -> Path:
    custom = os.environ.get("PICKLE_NETWORK_HOME")
    return Path(custom).expanduser() if custom else Path.home() / ".pickle-network"


def ensure_home() -> Path:
    root = home()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    for name in ("jobs", "logs", "keys"):
        (root / name).mkdir(mode=0o700, exist_ok=True)
    return root


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def write_private(path: Path, data) -> None:
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    raw = data.encode("utf-8") if isinstance(data, str) else data
    fd, temp = tempfile.mkstemp(prefix="." + path.name + ".", dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    except BaseException:
        try:
            os.unlink(temp)
        except FileNotFoundError:
            pass
        raise


def read_json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text("utf-8"))
    except FileNotFoundError:
        return default


def write_json(path: Path, value) -> None:
    write_private(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def default_config() -> dict:
    user_home = str(Path.home())
    return {
        "port": DEFAULT_PORT,
        "concurrency": 3,
        "max_queued": 100,
        "roots": [user_home],
        "default_cwd": user_home,
        "default_timeout": 3600,
        "max_timeout": 86400,
        "max_output_bytes": 16 * 1024 * 1024,
        "retention_days": 14,
        "public_url": None,
        "tunnel": {"mode": None},
    }


def load_config() -> dict:
    config = default_config()
    stored = read_json(home() / "config.json", {}) or {}
    config.update(stored)
    return config


def save_config(config: dict) -> None:
    write_json(home() / "config.json", config)
