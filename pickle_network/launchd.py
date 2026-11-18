from __future__ import annotations

import os
import plistlib
import re
import subprocess
import sys
from pathlib import Path

from .paths import home, repo_root

SERVER_LABEL = "network.pickle.server"
TUNNEL_LABEL = "network.pickle.tunnel"


def agents_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def plist_path(label: str) -> Path:
    return agents_dir() / (label + ".plist")


def domain() -> str:
    return "gui/%d" % os.getuid()


def _launchctl(*args) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True)


def write_plist(label: str, program: list, env: dict = None, log_name: str = None) -> Path:
    logs = home() / "logs"
    value = {
        "Label": label,
        "ProgramArguments": program,
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 10,
        "WorkingDirectory": str(repo_root()),
        "StandardOutPath": str(logs / ((log_name or label) + ".out.log")),
        "StandardErrorPath": str(logs / ((log_name or label) + ".err.log")),
        "EnvironmentVariables": {"PYTHONPATH": str(repo_root()), "PICKLE_NETWORK_HOME": str(home()),
                                 "PYTHONUNBUFFERED": "1", **(env or {})},
    }
    path = plist_path(label)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as sink:
        plistlib.dump(value, sink)
    os.chmod(path, 0o600)
    return path


def server_program() -> list:
    return [sys.executable, "-m", "pickle_network", "serve"]


def load(label: str) -> tuple:
    _launchctl("bootout", "%s/%s" % (domain(), label))
    _launchctl("enable", "%s/%s" % (domain(), label))
    done = _launchctl("bootstrap", domain(), str(plist_path(label)))
    return done.returncode == 0, (done.stderr or done.stdout).strip()


def unload(label: str, disable: bool = False) -> bool:
    done = _launchctl("bootout", "%s/%s" % (domain(), label))
    if disable:
        _launchctl("disable", "%s/%s" % (domain(), label))
    return done.returncode == 0


def remove(label: str) -> None:
    unload(label)
    try:
        plist_path(label).unlink()
    except FileNotFoundError:
        pass


def status(label: str) -> dict:
    done = _launchctl("print", "%s/%s" % (domain(), label))
    if done.returncode != 0:
        return {"loaded": False, "installed": plist_path(label).exists()}
    state = re.search(r"^\s*state = (\S+)", done.stdout, re.M)
    pid = re.search(r"^\s*pid = (\d+)", done.stdout, re.M)
    last = re.search(r"^\s*last exit code = (.+)$", done.stdout, re.M)
    return {"loaded": True, "installed": True, "state": state.group(1) if state else None,
            "pid": int(pid.group(1)) if pid else None, "last_exit": last.group(1).strip() if last else None}
