from __future__ import annotations

import re
import shutil
from pathlib import Path

from . import launchd
from .paths import home, write_private

QUICK_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
CANDIDATES = ("/opt/homebrew/bin/cloudflared", "/usr/local/bin/cloudflared")


def cloudflared() -> str:
    found = shutil.which("cloudflared")
    if found:
        return found
    for candidate in CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return None


def install_quick(port: int) -> Path:
    binary = cloudflared()
    if not binary:
        raise FileNotFoundError("cloudflared가 없습니다. brew install cloudflared 후 다시 실행하세요")
    log = home() / "logs" / (launchd.TUNNEL_LABEL + ".err.log")
    if log.exists():
        log.write_text("")
    launchd.write_plist(launchd.TUNNEL_LABEL, [binary, "tunnel", "--no-autoupdate", "--url",
                                              "http://127.0.0.1:%d" % port])
    return launchd.plist_path(launchd.TUNNEL_LABEL)


def install_token(token_file: Path) -> Path:
    binary = cloudflared()
    if not binary:
        raise FileNotFoundError("cloudflared가 없습니다. brew install cloudflared 후 다시 실행하세요")
    target = home() / "keys" / "tunnel-token"
    source = Path(token_file).expanduser()
    if source.resolve() != target.resolve():
        write_private(target, source.read_text("utf-8").strip() + "\n")
    launchd.write_plist(launchd.TUNNEL_LABEL, [binary, "tunnel", "--no-autoupdate", "run",
                                              "--token-file", str(target)])
    return launchd.plist_path(launchd.TUNNEL_LABEL)


def quick_url() -> str:
    log = home() / "logs" / (launchd.TUNNEL_LABEL + ".err.log")
    if not log.exists():
        return None
    found = QUICK_URL.findall(log.read_text("utf-8", "replace"))
    return found[-1] if found else None
