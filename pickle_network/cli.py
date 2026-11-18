from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import CLIENT_URL, __version__, launchd, shellenv, tunnel
from . import client as pn
from .agents import Agents
from .devices import Devices
from .paths import (ensure_home, home, load_config, read_json, repo_root,
                    save_config, write_json, write_private)

OK, WARN, FAIL = "OK  ", "WARN", "FAIL"


def say(text: str = "") -> None:
    print(text, flush=True)


def line(mark: str, text: str) -> None:
    say("  [%s] %s" % (mark, text))


def local_token() -> str:
    path = home() / "keys" / "local-token"
    return path.read_text("utf-8").strip() if path.exists() else None


def ensure_local_token() -> str:
    token = local_token()
    if token and Devices(home() / "devices.json").verify(token):
        return token
    _, token = Devices(home() / "devices.json").create("local", "full")
    write_private(home() / "keys" / "local-token", token + "\n")
    return token


def local_client(config: dict = None) -> pn.Client:
    config = config or load_config()
    token = local_token()
    if not token:
        raise SystemExit("설치되지 않았습니다. 먼저 pickle-network setup 을 실행하세요")
    return pn.Client({"url": "http://127.0.0.1:%d" % config["port"], "token": token})


def port_in_use(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def wait_healthy(config: dict, seconds: float = 20) -> dict:
    deadline = time.monotonic() + seconds
    last = None
    while time.monotonic() < deadline:
        try:
            status, value = local_client(config).request("GET", "/v1/health", timeout=3)
            if status == 200:
                return value
            last = value
        except OSError as exc:
            last = {"error": str(exc)}
        time.sleep(0.5)
    raise RuntimeError("서버가 응답하지 않습니다: %s" % last)


def access_secret() -> dict:
    return read_json(home() / "keys" / "access.json") or {}


def remote_config(token: str, config: dict) -> dict:
    value = {"url": config["public_url"], "token": token}
    secret = access_secret()
    if secret.get("client_id"):
        value["access"] = {"client_id": secret["client_id"], "client_secret": secret["client_secret"]}
    return value


def days_left(iso: str):
    if not iso:
        return None
    moment = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return (moment - datetime.now(timezone.utc)).total_seconds() / 86400


def cmd_setup(args) -> int:
    root = ensure_home()
    config = load_config()
    if args.port:
        config["port"] = args.port
    if args.root:
        config["roots"] = [str(Path(r).expanduser().resolve()) for r in args.root]
    if args.cwd:
        config["default_cwd"] = str(Path(args.cwd).expanduser().resolve())
    if args.concurrency:
        config["concurrency"] = args.concurrency
    save_config(config)
    say("pickle-network %s 설치" % __version__)
    line(OK, "데이터 폴더 %s" % root)
    env = shellenv.refresh()
    line(OK if env["source"] != "fallback" else WARN, "셸 PATH 수집 (%s, %s)" % (env["shell"], env["source"]))
    agents = Agents(env["path"]).detect(refresh=True)
    line(OK if agents else WARN, "AI CLI: " + (", ".join("%s %s" % (k, v["version"] or "") for k, v in agents.items()) or "없음"))
    ensure_local_token()
    line(OK, "로컬 관리 토큰 준비")
    if args.no_service:
        say("\n서비스 등록을 건너뛰었습니다. 직접 실행: pickle-network serve")
        return 0
    if launchd.status(launchd.SERVER_LABEL)["loaded"]:
        launchd.unload(launchd.SERVER_LABEL)
        time.sleep(1)
    if port_in_use(config["port"]):
        line(FAIL, "포트 %d을 다른 프로그램이 쓰고 있습니다. --port 로 바꾸세요" % config["port"])
        return 1
    launchd.write_plist(launchd.SERVER_LABEL, launchd.server_program())
    loaded, message = launchd.load(launchd.SERVER_LABEL)
    if not loaded:
        line(FAIL, "LaunchAgent 등록 실패: " + message)
        return 1
    health = wait_healthy(config)
    line(OK, "서버 실행 127.0.0.1:%d (작업자 %d개)" % (config["port"], health["workers_alive"]))
    if not args.no_link:
        link_command()
    say("\n다음 단계")
    say("  외부 연결:  pickle-network tunnel quick        (도메인 없이 바로)")
    say("              pickle-network tunnel token ...    (내 도메인, 상시 운영)")
    say("  피클 연결:  pickle-network pair")
    return 0


def link_command() -> None:
    target_dir = Path.home() / ".local" / "bin"
    target_dir.mkdir(parents=True, exist_ok=True)
    link = target_dir / "pickle-network"
    source = repo_root() / "bin" / "pickle-network"
    if link.is_symlink() or not link.exists():
        if link.is_symlink():
            link.unlink()
        link.symlink_to(source)
        on_path = str(target_dir) in os.environ.get("PATH", "").split(":")
        line(OK if on_path else WARN, "명령 연결 %s%s" % (link, "" if on_path else " (PATH에 ~/.local/bin 추가 필요)"))
    else:
        line(WARN, "%s 가 이미 있어 건너뜀" % link)


def cmd_serve(args) -> int:
    from .server import serve
    serve(args.port)
    return 0


def cmd_status(args) -> int:
    config = load_config()
    say("pickle-network %s" % __version__)
    server = launchd.status(launchd.SERVER_LABEL)
    tun = launchd.status(launchd.TUNNEL_LABEL)
    say("  서버     %s" % _svc(server))
    say("  터널     %s (%s)" % (_svc(tun), (config.get("tunnel") or {}).get("mode") or "없음"))
    say("  외부주소 %s" % (_public_url(config) or "-"))
    try:
        status, health = local_client(config).request("GET", "/v1/health", timeout=3)
        say("  응답     %s, 작업 %s" % (health.get("status") if status == 200 else status,
                                       json.dumps(health.get("jobs", {}), ensure_ascii=False)))
    except OSError:
        say("  응답     없음")
    devices = [d for d in Devices(home() / "devices.json").list() if not d["revoked"] and d["name"] != "local"]
    say("  연결기기 %s" % (", ".join("%s(%s)" % (d["name"], d["id"]) for d in devices) or "없음"))
    left = days_left(((config.get("tunnel") or {}).get("access") or {}).get("expires_at"))
    if left is not None:
        say("  Access   만료까지 %.1f일" % left)
    return 0


def _svc(info: dict) -> str:
    if not info["loaded"]:
        return "설치됨, 중지" if info["installed"] else "미설치"
    return "%s pid=%s" % (info.get("state"), info.get("pid"))


def _public_url(config: dict):
    mode = (config.get("tunnel") or {}).get("mode")
    if mode == "quick":
        return tunnel.quick_url()
    return config.get("public_url")


def cmd_doctor(args) -> int:
    config = load_config()
    failures = 0
    say("pickle-network 점검")
    mode = os.stat(home()).st_mode & 0o777 if home().exists() else None
    line(OK if mode == 0o700 else FAIL, "데이터 폴더 권한 %s" % (oct(mode) if mode else "없음"))
    failures += mode != 0o700
    server = launchd.status(launchd.SERVER_LABEL)
    line(OK if server.get("state") == "running" else FAIL, "서버 LaunchAgent " + _svc(server))
    failures += server.get("state") != "running"
    try:
        status, hello = local_client(config).request("GET", "/v1/hello", timeout=20)
        line(OK if status == 200 else FAIL, "로컬 API 응답 %s" % status)
        failures += status != 200
        line(OK if hello.get("agents") else WARN, "AI CLI " + json.dumps(hello.get("agents"), ensure_ascii=False))
    except OSError as exc:
        line(FAIL, "로컬 API 연결 실패: %s" % exc)
        failures += 1
    env = shellenv.stored()
    line(OK if env.get("source") == "interactive_login_shell" else WARN, "셸 PATH 출처 %s" % env.get("source"))
    tmode = (config.get("tunnel") or {}).get("mode")
    if not tmode:
        line(WARN, "터널 없음. 외부(피클)에서는 접속할 수 없습니다")
        return 1 if failures else 0
    tun = launchd.status(launchd.TUNNEL_LABEL)
    line(OK if tun.get("state") == "running" else FAIL, "터널 LaunchAgent " + _svc(tun))
    failures += tun.get("state") != "running"
    url = _public_url(config)
    if not url:
        line(FAIL, "외부 주소를 아직 모릅니다. 잠시 뒤 다시 실행하세요")
        return 1
    token = local_token()
    remote = dict(remote_config(token, config), url=url)
    failures += _remote_check(remote)
    left = days_left(((config.get("tunnel") or {}).get("access") or {}).get("expires_at"))
    if left is not None:
        line(OK if left > 7 else WARN if left > 0 else FAIL, "Access 서비스 토큰 만료까지 %.1f일" % left)
        failures += left <= 0
    return 1 if failures else 0


def _remote_check(remote: dict) -> int:
    failures = 0
    try:
        status, _ = pn.Client(remote).request("GET", "/v1/health", timeout=20)
        line(OK if status == 200 else FAIL, "외부 주소 인증 요청 %s → %s" % (remote["url"], status))
        failures += status != 200
        bad = dict(remote, token="pn_00000000_" + "x" * 43)
        status, value = pn.Client(bad).request("GET", "/v1/health", timeout=20)
        expected = (value.get("error") or {}).get("code") == "unauthorized"
        line(OK if expected else FAIL, "잘못된 기기 토큰 거절 %s" % status)
        failures += not expected
        if remote.get("access"):
            bare = {k: v for k, v in remote.items() if k != "access"}
            status, value = pn.Client(bare).request("GET", "/v1/health", timeout=20)
            blocked = status in (302, 401, 403) and value.get("service") != "pickle-network"
            line(OK if blocked else FAIL, "Access 없는 요청을 Cloudflare가 차단 %s" % status)
            failures += not blocked
    except OSError as exc:
        line(FAIL, "외부 주소 연결 실패: %s" % exc)
        failures += 1
    return failures


def cmd_tunnel(args) -> int:
    config = load_config()
    if args.tunnel_cmd == "quick":
        tunnel.install_quick(config["port"])
        config["tunnel"] = {"mode": "quick"}
        config["public_url"] = None
        save_config(config)
        loaded, message = launchd.load(launchd.TUNNEL_LABEL)
        if not loaded:
            say("터널 등록 실패: " + message)
            return 1
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline and not tunnel.quick_url():
            time.sleep(1)
        url = tunnel.quick_url()
        say("Quick Tunnel 주소: %s" % (url or "아직 없음. pickle-network status 로 확인"))
        say("이 주소는 터널을 다시 시작하면 바뀝니다. 바뀌면 pickle-network pair 를 다시 실행하세요")
        say("Access 없이 기기 토큰 한 층으로만 보호됩니다. 시험용으로 쓰세요")
        return 0 if url else 1
    if args.tunnel_cmd == "token":
        tunnel.install_token(Path(args.token_file))
        tconf = {"mode": "token", "hostname": args.hostname}
        if args.access_id:
            if not args.access_secret_file:
                say("--access-id 에는 --access-secret-file 이 필요합니다")
                return 1
            secret = Path(args.access_secret_file).expanduser().read_text("utf-8").strip()
            write_json(home() / "keys" / "access.json", {"client_id": args.access_id, "client_secret": secret,
                                                         "expires_at": args.access_expires})
            tconf["access"] = {"client_id": args.access_id, "expires_at": args.access_expires}
        config["tunnel"] = tconf
        config["public_url"] = "https://" + args.hostname
        save_config(config)
        loaded, message = launchd.load(launchd.TUNNEL_LABEL)
        say("터널 등록 %s %s" % ("완료" if loaded else "실패", message))
        say("외부 주소: %s" % config["public_url"])
        return 0 if loaded else 1
    if args.tunnel_cmd == "off":
        launchd.remove(launchd.TUNNEL_LABEL)
        config["tunnel"] = {"mode": None}
        config["public_url"] = None
        save_config(config)
        say("터널을 내렸습니다")
        return 0
    return cmd_status(args)


PAIR_TEMPLATE = """내 맥과 pickle-network로 연결해 줘. 아래 순서대로 실행하고 결과를 알려줘.

1. 클라이언트 받기
curl -fsSL {client_url} -o pn.py

2. 연결 정보 저장{key_note}
python3 pn.py connect '{bundle}'{key_arg}

3. 사용 규칙 읽기 (앞으로 맥 작업은 이 규칙을 따라)
python3 pn.py guide

4. 연결 확인
python3 pn.py hello

hello 결과의 맥 이름과 AI CLI 목록을 알려줘. 연결 정보 문자열과 저장된 설정 파일 내용은 비밀이니 출력하거나 다른 곳에 보내지 마."""

KEYGEN_PROMPT = """pickle-network 연결용 키를 만들어 줘. 아래를 실행하고 public_key 값(-----BEGIN PUBLIC KEY----- 부터 끝까지)만 그대로 보여줘. 개인키는 보여주지 마.

curl -fsSL {client_url} -o pn.py
python3 pn.py keygen"""


def cmd_pair(args) -> int:
    config = load_config()
    url = args.url or _public_url(config)
    if not url:
        say("외부 주소가 없습니다. 먼저 pickle-network tunnel quick 또는 tunnel token 을 실행하세요")
        return 1
    recipient = home() / "keys" / ("recipient-%s.pem" % args.name)
    if args.key:
        pem = sys.stdin.read() if args.key == "-" else Path(args.key).expanduser().read_text("ascii")
        pn.load_public_key(pem)
        write_private(recipient, pem.strip() + "\n")
    if not args.plain and not recipient.exists():
        say("피클의 공개키가 필요합니다. 아래 문장을 피클에게 보내고, 받은 공개키를 파일로 저장한 뒤")
        say("  pickle-network pair --name %s --key 공개키파일" % args.name)
        say("을 실행하세요. 공개키 없이 시험만 하려면 --plain 을 붙이세요.\n")
        say(KEYGEN_PROMPT.format(client_url=CLIENT_URL))
        return 2
    devices = Devices(home() / "devices.json")
    if args.replace:
        devices.revoke(args.name)
    device, token = devices.create(args.name, "read" if args.read_only else "full")
    payload = remote_config(token, dict(config, public_url=url))
    payload.update({"name": args.name, "issued": int(time.time())})
    if args.plain:
        bundle = pn.plain_bundle(payload)
        key_note, key_arg = "", ""
    else:
        bundle = pn.seal(payload, recipient.read_text("ascii"))
        key_note = " (개인키가 기본 위치 ~/.pickle-network-client/key.pem 이 아니면 --key 로 경로 지정)"
        key_arg = ""
    message = PAIR_TEMPLATE.format(client_url=CLIENT_URL, bundle=bundle, key_note=key_note, key_arg=key_arg)
    say("기기 '%s'(%s, %s) 토큰을 만들었습니다%s." % (device["name"], device["id"], device["scope"],
                                                 "" if not args.plain else ", 암호화하지 않은 연결 정보입니다"))
    if args.copy and shutil.which("pbcopy"):
        subprocess.run(["pbcopy"], input=message.encode("utf-8"))
        say("피클에게 보낼 메시지를 클립보드에 복사했습니다.\n")
    say("----- 피클에게 보낼 메시지 -----")
    say(message)
    say("--------------------------------")
    return 0


def cmd_devices(args) -> int:
    devices = Devices(home() / "devices.json")
    if args.devices_cmd == "revoke":
        hits = devices.revoke(args.key)
        say("폐기: %s" % (", ".join("%s(%s)" % (d["name"], d["id"]) for d in hits) or "대상 없음"))
        return 0 if hits else 1
    for d in devices.list():
        seen = datetime.fromtimestamp(d["last_seen"]).strftime("%Y-%m-%d %H:%M") if d["last_seen"] else "-"
        say("%s  %-12s %-4s 마지막 접속 %s%s" % (d["id"], d["name"], d["scope"], seen, "  [폐기됨]" if d["revoked"] else ""))
    return 0


def cmd_run(args) -> int:
    body = {"command": args.command, "cwd": args.cwd, "timeout": args.timeout}
    status, value = pn._submit(local_client(), "/v1/run", {k: v for k, v in body.items() if v is not None}, args.wait)
    return pn._emit(status, value)


def cmd_ask(args) -> int:
    body = {"prompt": args.prompt, "agent": args.agent, "mode": args.mode, "cwd": args.cwd, "model": args.model}
    status, value = pn._submit(local_client(), "/v1/ask", {k: v for k, v in body.items() if v is not None}, args.wait)
    return pn._emit(status, value)


def cmd_logs(args) -> int:
    name = {"server": launchd.SERVER_LABEL + ".err.log", "access": "access.log",
            "tunnel": launchd.TUNNEL_LABEL + ".err.log"}[args.which]
    path = home() / "logs" / name
    if not path.exists():
        say("로그가 없습니다: %s" % path)
        return 1
    os.execvp("tail", ["tail", "-n", str(args.lines)] + (["-f"] if args.follow else []) + [str(path)])
    return 0


def cmd_stop(args) -> int:
    for label in (launchd.TUNNEL_LABEL, launchd.SERVER_LABEL):
        launchd.unload(label, disable=True)
    say("서버와 터널을 중지했습니다. 다시 켜려면 pickle-network start")
    say("유출이 의심되면 pickle-network devices revoke <이름> 으로 기기 토큰도 폐기하세요")
    return 0


def cmd_start(args) -> int:
    code = 0
    for label in (launchd.SERVER_LABEL, launchd.TUNNEL_LABEL):
        if launchd.plist_path(label).exists():
            loaded, message = launchd.load(label)
            say("%s %s %s" % (label, "시작" if loaded else "실패", message))
            code |= not loaded
    return code


def cmd_uninstall(args) -> int:
    for label in (launchd.TUNNEL_LABEL, launchd.SERVER_LABEL):
        launchd.remove(label)
    link = Path.home() / ".local" / "bin" / "pickle-network"
    if link.is_symlink() and Path(os.readlink(link)) == repo_root() / "bin" / "pickle-network":
        link.unlink()
    say("서비스와 명령 연결을 제거했습니다")
    if args.purge and home().exists():
        trash = Path.home() / ".Trash" / ("pickle-network-data-%d" % int(time.time()))
        shutil.move(str(home()), str(trash))
        say("데이터 폴더를 휴지통으로 옮겼습니다: %s" % trash)
    else:
        say("데이터 폴더는 남겨 두었습니다: %s (지우려면 --purge)" % home())
    return 0


def build_parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="pickle-network", description="피클과 내 맥을 잇는 실행 서버")
    root.add_argument("--version", action="version", version=__version__)
    sub = root.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("setup", help="설치 또는 설정 갱신")
    p.add_argument("--port", type=int)
    p.add_argument("--root", action="append", help="파일 API 허용 폴더 (반복 가능, 기본 홈)")
    p.add_argument("--cwd", help="기본 작업 폴더")
    p.add_argument("--concurrency", type=int)
    p.add_argument("--no-service", action="store_true")
    p.add_argument("--no-link", action="store_true")
    p.set_defaults(func=cmd_setup)

    p = sub.add_parser("serve", help="포그라운드 실행")
    p.add_argument("--port", type=int)
    p.set_defaults(func=cmd_serve)

    sub.add_parser("status", help="상태 요약").set_defaults(func=cmd_status)
    sub.add_parser("doctor", help="연결 점검").set_defaults(func=cmd_doctor)

    p = sub.add_parser("tunnel", help="외부 연결")
    tsub = p.add_subparsers(dest="tunnel_cmd", required=True)
    tsub.add_parser("quick", help="Cloudflare Quick Tunnel (도메인 불필요)")
    t = tsub.add_parser("token", help="Cloudflare 대시보드에서 만든 터널 토큰 사용")
    t.add_argument("--token-file", required=True)
    t.add_argument("--hostname", required=True)
    t.add_argument("--access-id")
    t.add_argument("--access-secret-file")
    t.add_argument("--access-expires", help="ISO 8601 만료 시각")
    tsub.add_parser("off", help="터널 제거")
    tsub.add_parser("status")
    p.set_defaults(func=cmd_tunnel)

    p = sub.add_parser("pair", help="피클에게 보낼 연결 메시지 만들기")
    p.add_argument("--name", default="pickle")
    p.add_argument("--key", help="피클 공개키 PEM 파일, - 이면 표준입력")
    p.add_argument("--plain", action="store_true", help="암호화 없이 (시험용)")
    p.add_argument("--read-only", action="store_true")
    p.add_argument("--replace", action="store_true", help="같은 이름의 기존 토큰 폐기")
    p.add_argument("--copy", action="store_true", help="클립보드에 복사")
    p.add_argument("--url", help="외부 주소 직접 지정")
    p.set_defaults(func=cmd_pair)

    p = sub.add_parser("devices", help="연결 기기 관리")
    dsub = p.add_subparsers(dest="devices_cmd")
    dsub.add_parser("list")
    r = dsub.add_parser("revoke")
    r.add_argument("key", help="기기 ID 또는 이름")
    p.set_defaults(func=cmd_devices)

    p = sub.add_parser("run", help="로컬 시험 실행")
    p.add_argument("command")
    p.add_argument("--cwd")
    p.add_argument("--timeout", type=int)
    p.add_argument("--wait", type=float, default=120)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("ask", help="로컬 AI CLI 위임 시험")
    p.add_argument("prompt")
    p.add_argument("--agent", default="auto")
    p.add_argument("--mode", default="read", choices=("read", "edit", "full"))
    p.add_argument("--model")
    p.add_argument("--cwd")
    p.add_argument("--wait", type=float, default=600)
    p.set_defaults(func=cmd_ask)

    p = sub.add_parser("logs", help="로그 보기")
    p.add_argument("which", nargs="?", default="server", choices=("server", "access", "tunnel"))
    p.add_argument("-n", "--lines", type=int, default=50)
    p.add_argument("-f", "--follow", action="store_true")
    p.set_defaults(func=cmd_logs)

    sub.add_parser("stop", help="긴급 중지").set_defaults(func=cmd_stop)
    sub.add_parser("start", help="다시 시작").set_defaults(func=cmd_start)

    p = sub.add_parser("uninstall", help="제거")
    p.add_argument("--purge", action="store_true")
    p.set_defaults(func=cmd_uninstall)
    return root


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0
    except (RuntimeError, FileNotFoundError, ValueError) as exc:
        say("오류: %s" % exc)
        return 1
