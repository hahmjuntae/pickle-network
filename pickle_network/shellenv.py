from __future__ import annotations

import os
import pwd
import subprocess
import time
from pathlib import Path

from .paths import home, read_json, write_json

MARK = "__PICKLE_NETWORK_PATH__"
EXTRA_DIRS = ("~/.local/bin", "/opt/homebrew/bin", "/opt/homebrew/sbin", "/usr/local/bin",
              "/usr/bin", "/bin", "/usr/sbin", "/sbin")


def login_shell() -> str:
    shell = pwd.getpwuid(os.getuid()).pw_shell or "/bin/zsh"
    return shell if Path(shell).exists() else "/bin/sh"


def _merge(path: str) -> str:
    seen, parts = set(), []
    for item in path.split(":") + [os.path.expanduser(d) for d in EXTRA_DIRS]:
        if item and item not in seen:
            seen.add(item)
            parts.append(item)
    return ":".join(parts)


def capture_path(timeout: float = 20) -> tuple:
    shell = login_shell()
    user = pwd.getpwuid(os.getuid())
    env = {"HOME": user.pw_dir, "USER": user.pw_name, "LOGNAME": user.pw_name, "SHELL": shell,
           "TERM": "dumb", "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}
    script = "printf '%s%%s%s' \"$PATH\"" % (MARK, MARK)
    try:
        done = subprocess.run([shell, "-ilc", script], env=env, stdin=subprocess.DEVNULL,
                              capture_output=True, timeout=timeout, start_new_session=True)
        text = done.stdout.decode("utf-8", "replace")
        if text.count(MARK) >= 2:
            return _merge(text.split(MARK)[-2]), "interactive_login_shell"
    except (OSError, subprocess.TimeoutExpired):
        pass
    return _merge(os.environ.get("PATH", "")), "fallback"


def refresh() -> dict:
    path, source = capture_path()
    record = {"path": path, "source": source, "shell": login_shell(), "captured_at": time.time()}
    write_json(home() / "env.json", record)
    return record


def stored() -> dict:
    return read_json(home() / "env.json") or {"path": _merge(os.environ.get("PATH", "")),
                                               "source": "process", "shell": login_shell()}


def build_env(path: str) -> dict:
    user = pwd.getpwuid(os.getuid())
    env = {"HOME": user.pw_dir, "USER": user.pw_name, "LOGNAME": user.pw_name,
           "SHELL": login_shell(), "PATH": path, "TERM": "dumb", "NO_COLOR": "1",
           "LANG": os.environ.get("LANG") or "en_US.UTF-8", "PICKLE_NETWORK": "1"}
    for key in ("TMPDIR", "LC_ALL", "SSH_AUTH_SOCK"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    return env
