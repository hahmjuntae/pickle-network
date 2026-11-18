from __future__ import annotations

import shutil
import subprocess
import threading
import time

from .shellenv import build_env

MODES = ("read", "edit", "full")
ORDER = ("claude", "codex", "gemini", "agy")


def _claude(binary, prompt, mode, model):
    argv = [binary, "-p", prompt, "--output-format", "text"]
    argv += {"read": [], "edit": ["--permission-mode", "acceptEdits"],
             "full": ["--dangerously-skip-permissions"]}[mode]
    return argv + (["--model", model] if model else [])


def _codex(binary, prompt, mode, model):
    argv = [binary, "exec", "--skip-git-repo-check"]
    argv += {"read": ["-s", "read-only"], "edit": ["--full-auto"],
             "full": ["--dangerously-bypass-approvals-and-sandbox"]}[mode]
    argv += ["-m", model] if model else []
    return argv + [prompt if not prompt.startswith("-") else " " + prompt]


def _gemini(binary, prompt, mode, model):
    argv = [binary]
    argv += {"read": ["--approval-mode", "default"], "edit": ["--approval-mode", "auto_edit"],
             "full": ["--yolo"]}[mode]
    argv += ["-m", model] if model else []
    return argv + ["-p", prompt]


def _agy(binary, prompt, mode, model):
    argv = [binary, "-p", prompt]
    argv += {"read": ["--mode", "plan"], "edit": ["--mode", "accept-edits"],
             "full": ["--dangerously-skip-permissions"]}[mode]
    return argv + (["--model", model] if model else [])


BUILDERS = {"claude": _claude, "codex": _codex, "gemini": _gemini, "agy": _agy}


class Agents:
    def __init__(self, path_value: str):
        self.path_value = path_value
        self.lock = threading.Lock()
        self.cache = None
        self.cached_at = 0.0

    def detect(self, refresh: bool = False) -> dict:
        with self.lock:
            if self.cache is not None and not refresh and time.time() - self.cached_at < 600:
                return self.cache
            found = {}
            for name in ORDER:
                binary = shutil.which(name, path=self.path_value)
                if not binary:
                    continue
                version = None
                try:
                    done = subprocess.run([binary, "--version"], capture_output=True, timeout=40,
                                          stdin=subprocess.DEVNULL, env=build_env(self.path_value))
                    lines = (done.stdout or done.stderr).decode("utf-8", "replace").strip().splitlines()
                    if done.returncode == 0 and lines:
                        version = lines[0][:120]
                except (OSError, subprocess.TimeoutExpired):
                    pass
                found[name] = {"path": binary, "version": version}
            self.cache, self.cached_at = found, time.time()
            return found

    def build(self, agent: str, prompt: str, mode: str = "edit", model: str = None) -> tuple:
        if mode not in MODES:
            raise ValueError("mode는 read, edit, full 중 하나입니다")
        installed = self.detect()
        if agent in (None, "", "auto"):
            agent = next((name for name in ORDER if name in installed), None)
            if not agent:
                raise LookupError("설치된 AI CLI가 없습니다")
        if agent not in BUILDERS:
            raise ValueError("지원하는 agent: auto, " + ", ".join(ORDER))
        if agent not in installed:
            raise LookupError("%s CLI를 찾지 못했습니다" % agent)
        return agent, BUILDERS[agent](installed[agent]["path"], prompt, mode, model)
