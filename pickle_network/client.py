#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import time
import urllib.parse
import http.client
from pathlib import Path

CLIENT_VERSION = "1.0.0"
BUNDLE_PLAIN = "pn1."
BUNDLE_SEALED = "pn1e."
DEFAULT_DIR = Path(os.environ.get("PN_HOME") or Path.home() / ".pickle-network-client")
USER_AGENT = "pickle-network-client/" + CLIENT_VERSION



def _der_read(data: bytes, pos: int):
    tag = data[pos]
    length = data[pos + 1]
    pos += 2
    if length & 0x80:
        count = length & 0x7F
        length = int.from_bytes(data[pos:pos + count], "big")
        pos += count
    return tag, data[pos:pos + length], pos + length


def _der_items(data: bytes) -> list:
    items, pos = [], 0
    while pos < len(data):
        tag, value, pos = _der_read(data, pos)
        items.append((tag, value))
    return items


def _der_len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(raw)]) + raw


def _der(tag: int, value: bytes) -> bytes:
    return bytes([tag]) + _der_len(len(value)) + value


def _der_int(n: int) -> bytes:
    raw = n.to_bytes(n.bit_length() // 8 + 1, "big")
    return _der(0x02, raw)


RSA_OID = _der(0x06, bytes.fromhex("2a864886f70d010101")) + _der(0x05, b"")


def _pem_body(text: str) -> tuple:
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    if len(lines) < 3 or not lines[0].startswith("-----BEGIN ") or not lines[-1].startswith("-----END "):
        raise ValueError("PEM 형식이 아닙니다")
    label = lines[0][11:].rstrip("-").strip()
    return label, base64.b64decode("".join(lines[1:-1]))


def load_public_key(text: str) -> tuple:
    label, der = _pem_body(text)
    if label == "PUBLIC KEY":
        outer = _der_items(_der_items(der)[0][1])
        bits = outer[1][1]
        der = bits[1:]
    elif label != "RSA PUBLIC KEY":
        raise ValueError("RSA 공개키가 아닙니다")
    fields = _der_items(_der_items(der)[0][1])
    return int.from_bytes(fields[0][1], "big"), int.from_bytes(fields[1][1], "big")


def load_private_key(text: str) -> tuple:
    label, der = _pem_body(text)
    if label == "PRIVATE KEY":
        items = _der_items(_der_items(der)[0][1])
        der = items[2][1]
    elif label != "RSA PRIVATE KEY":
        raise ValueError("암호화되지 않은 RSA 개인키(PEM)가 필요합니다")
    fields = [int.from_bytes(v, "big") for _, v in _der_items(_der_items(der)[0][1])]
    n, e, d, p, q = fields[1], fields[2], fields[3], fields[4], fields[5]
    return n, e, d, p, q


def _mgf1(seed: bytes, length: int) -> bytes:
    out, counter = b"", 0
    while len(out) < length:
        out += hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
        counter += 1
    return out[:length]


def _xor(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


def oaep_encrypt(public: tuple, message: bytes) -> bytes:
    n, e = public
    k = (n.bit_length() + 7) // 8
    h = hashlib.sha256(b"").digest()
    if len(message) > k - 2 * len(h) - 2:
        raise ValueError("RSA 한 블록에 비해 데이터가 깁니다")
    db = h + b"\x00" * (k - len(message) - 2 * len(h) - 2) + b"\x01" + message
    seed = secrets.token_bytes(len(h))
    masked_db = _xor(db, _mgf1(seed, k - len(h) - 1))
    masked_seed = _xor(seed, _mgf1(masked_db, len(h)))
    m = int.from_bytes(b"\x00" + masked_seed + masked_db, "big")
    return pow(m, e, n).to_bytes(k, "big")


def oaep_decrypt(private: tuple, cipher: bytes) -> bytes:
    n, _, d, p, q = private
    k = (n.bit_length() + 7) // 8
    c = int.from_bytes(cipher, "big")
    m1, m2 = pow(c, d % (p - 1), p), pow(c, d % (q - 1), q)
    m = m2 + q * ((pow(q, -1, p) * (m1 - m2)) % p)
    em = m.to_bytes(k, "big")
    h = hashlib.sha256(b"").digest()
    masked_seed, masked_db = em[1:1 + len(h)], em[1 + len(h):]
    seed = _xor(masked_seed, _mgf1(masked_db, len(h)))
    db = _xor(masked_db, _mgf1(seed, k - len(h) - 1))
    rest = db[len(h):].lstrip(b"\x00")
    if em[0] != 0 or not hmac.compare_digest(db[:len(h)], h) or not rest.startswith(b"\x01"):
        raise ValueError("이 개인키로 열 수 없는 연결 정보입니다")
    return rest[1:]


def _probable_prime(n: int) -> bool:
    if n < 2:
        return False
    for small in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        if n % small == 0:
            return n == small
    d, r = n - 1, 0
    while d % 2 == 0:
        d //= 2
        r += 1
    for _ in range(40):
        x = pow(secrets.randbelow(n - 3) + 2, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def _prime(bits: int) -> int:
    while True:
        candidate = secrets.randbits(bits) | (1 << (bits - 1)) | (1 << (bits - 2)) | 1
        if _probable_prime(candidate):
            return candidate


def generate_private_pem(bits: int = 3072) -> str:
    openssl = shutil.which("openssl")
    if openssl:
        done = subprocess.run([openssl, "genrsa", str(bits)], capture_output=True, timeout=120)
        if done.returncode == 0 and b"PRIVATE KEY" in done.stdout:
            return done.stdout.decode("ascii")
    e = 65537
    while True:
        p, q = _prime(bits // 2), _prime(bits // 2)
        phi = (p - 1) * (q - 1)
        if p != q and phi % e:
            break
    n, d = p * q, pow(e, -1, phi)
    seq = b"".join(_der_int(x) for x in (0, n, e, d, p, q, d % (p - 1), d % (q - 1), pow(q, -1, p)))
    der = _der(0x30, seq)
    body = base64.encodebytes(der).decode("ascii").replace("\n", "")
    lines = [body[i:i + 64] for i in range(0, len(body), 64)]
    return "-----BEGIN RSA PRIVATE KEY-----\n" + "\n".join(lines) + "\n-----END RSA PRIVATE KEY-----\n"


def public_pem_from_private(private: tuple) -> str:
    n, e = private[0], private[1]
    rsa = _der(0x30, _der_int(n) + _der_int(e))
    spki = _der(0x30, _der(0x30, RSA_OID) + _der(0x03, b"\x00" + rsa))
    body = base64.b64encode(spki).decode("ascii")
    lines = [body[i:i + 64] for i in range(0, len(body), 64)]
    return "-----BEGIN PUBLIC KEY-----\n" + "\n".join(lines) + "\n-----END PUBLIC KEY-----\n"



def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    out, counter = b"", 0
    while len(out) < length:
        out += hmac.new(key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest()
        counter += 1
    return out[:length]


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64u(text: str) -> bytes:
    text = "".join(text.split())
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def seal(payload: dict, public_pem: str) -> str:
    public = load_public_key(public_pem)
    key, nonce = secrets.token_bytes(32), secrets.token_bytes(16)
    enc_key = hmac.new(key, b"pn-enc", hashlib.sha256).digest()
    mac_key = hmac.new(key, b"pn-mac", hashlib.sha256).digest()
    plain = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    body = _xor(plain, _keystream(enc_key, nonce, len(plain)))
    wrapped = oaep_encrypt(public, key)
    tag = hmac.new(mac_key, wrapped + nonce + body, hashlib.sha256).digest()
    blob = len(wrapped).to_bytes(2, "big") + wrapped + nonce + tag + body
    return BUNDLE_SEALED + _b64u(blob)


def open_bundle(bundle: str, private_pem: str = None) -> dict:
    bundle = "".join(bundle.split())
    if bundle.startswith(BUNDLE_PLAIN):
        return json.loads(_unb64u(bundle[len(BUNDLE_PLAIN):]))
    if not bundle.startswith(BUNDLE_SEALED):
        raise ValueError("pn1. 또는 pn1e. 로 시작하는 연결 정보가 필요합니다")
    if not private_pem:
        raise ValueError("암호화된 연결 정보입니다. --key로 개인키를 지정하세요")
    blob = _unb64u(bundle[len(BUNDLE_SEALED):])
    size = int.from_bytes(blob[:2], "big")
    wrapped, rest = blob[2:2 + size], blob[2 + size:]
    nonce, tag, body = rest[:16], rest[16:48], rest[48:]
    key = oaep_decrypt(load_private_key(private_pem), wrapped)
    enc_key = hmac.new(key, b"pn-enc", hashlib.sha256).digest()
    mac_key = hmac.new(key, b"pn-mac", hashlib.sha256).digest()
    if not hmac.compare_digest(tag, hmac.new(mac_key, wrapped + nonce + body, hashlib.sha256).digest()):
        raise ValueError("연결 정보가 손상됐습니다")
    return json.loads(_xor(body, _keystream(enc_key, nonce, len(body))))


def plain_bundle(payload: dict) -> str:
    return BUNDLE_PLAIN + _b64u(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))



def _doh_lookup(host: str) -> list:
    conn = http.client.HTTPSConnection("1.1.1.1", timeout=10, context=ssl.create_default_context())
    conn.request("GET", "/dns-query?" + urllib.parse.urlencode({"name": host, "type": "A"}),
                 headers={"Accept": "application/dns-json", "User-Agent": USER_AGENT})
    response = conn.getresponse()
    data = json.loads(response.read(65536))
    conn.close()
    addresses = [a["data"] for a in data.get("Answer", []) if a.get("type") == 1]
    return [a for a in addresses if ipaddress.ip_address(a).is_global]


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address, **kwargs):
        super().__init__(host, **kwargs)
        self.address = address

    def connect(self):
        sock = socket.create_connection((self.address, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class Client:
    def __init__(self, config: dict):
        url = urllib.parse.urlsplit(config["url"])
        if url.scheme not in ("http", "https") or not url.hostname:
            raise ValueError("url이 올바르지 않습니다")
        if url.scheme == "http" and url.hostname not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("원격 주소는 https만 허용합니다")
        self.config = config
        self.url = url
        self.address = None

    def _connection(self, timeout: float):
        port = self.url.port
        if self.url.scheme == "http":
            return http.client.HTTPConnection(self.url.hostname, port or 80, timeout=timeout)
        context = ssl.create_default_context()
        if self.address:
            return _PinnedHTTPS(self.url.hostname, self.address, port=port or 443, timeout=timeout, context=context)
        return http.client.HTTPSConnection(self.url.hostname, port or 443, timeout=timeout, context=context)

    def request(self, method: str, path: str, body=None, query: dict = None, timeout: float = 120) -> tuple:
        headers = {"Authorization": "Bearer " + self.config["token"], "Accept": "application/json",
                   "User-Agent": USER_AGENT}
        access = self.config.get("access") or {}
        if access.get("client_id"):
            headers["CF-Access-Client-Id"] = access["client_id"]
            headers["CF-Access-Client-Secret"] = access["client_secret"]
        payload = None
        if body is not None:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if query:
            path += "?" + urllib.parse.urlencode({k: v for k, v in query.items() if v is not None})
        for attempt in range(2):
            conn = self._connection(timeout)
            try:
                conn.request(method, path, body=payload, headers=headers)
                response = conn.getresponse()
                raw = response.read(32 * 1024 * 1024)
                status = response.status
                break
            except socket.gaierror:
                if attempt or self.url.scheme != "https":
                    raise
                addresses = _doh_lookup(self.url.hostname)
                if not addresses:
                    raise
                self.address = addresses[0]
            finally:
                conn.close()
        try:
            value = json.loads(raw)
        except ValueError:
            value = {"ok": False, "error": {"code": "non_json_response", "status": status,
                                            "message": raw[:300].decode("utf-8", "replace")}}
        if status in (401, 403) and not (isinstance(value, dict) and value.get("service") == "pickle-network"):
            value = {"ok": False, "error": {"code": "blocked_before_mac", "status": status,
                                            "message": "Cloudflare Access 등 맥 앞단에서 거절했습니다"}}
        return status, value



def mac_path(value):
    if not value:
        return value
    local_home = str(Path.home()).rstrip("/")
    if local_home and value == local_home:
        return "~"
    if local_home and value.startswith(local_home + "/"):
        return "~" + value[len(local_home):]
    return value


def _config_path(args) -> Path:
    return Path(args.config or os.environ.get("PN_CONFIG") or DEFAULT_DIR / "config.json")


def _write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as sink:
        sink.write(text)
    os.chmod(path, 0o600)


def _load_config(args) -> dict:
    path = _config_path(args)
    if not path.exists():
        raise SystemExit(_fail("not_connected", "연결 설정이 없습니다. 먼저 connect를 실행하세요: " + str(path)))
    return json.loads(path.read_text("utf-8"))


def _fail(code: str, message: str) -> int:
    print(json.dumps({"ok": False, "error": {"code": code, "message": message}}, ensure_ascii=False, indent=2))
    return 1


def _emit(status: int, value: dict) -> int:
    print(json.dumps(value, ensure_ascii=False, indent=2))
    if status >= 400 or not value.get("ok", False):
        return 1
    job = value.get("job") or {}
    if job.get("state") in ("queued", "running"):
        return 2
    if job.get("state") and job.get("state") != "succeeded":
        return 1
    return 0


def _follow(client: Client, value: dict, wait: float) -> tuple:
    status = 200
    deadline = time.monotonic() + wait
    job = value.get("job") or {}
    while job.get("state") in ("queued", "running") and time.monotonic() < deadline:
        step = max(1, min(50, int(deadline - time.monotonic())))
        try:
            status, value = client.request("GET", "/v1/jobs/" + job["id"], query={"wait": step}, timeout=step + 30)
        except OSError:
            time.sleep(2)
            continue
        job = value.get("job") or job
    return status, value


def _submit(client: Client, path: str, body: dict, wait: float) -> tuple:
    body["request_id"] = body.get("request_id") or "pn-" + secrets.token_hex(8)
    body["wait"] = max(0, min(50, int(wait)))
    value, status = None, 0
    for attempt in range(4):
        try:
            status, value = client.request("POST", path, body=body, timeout=body["wait"] + 30)
            break
        except OSError:
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))
    if wait > body["wait"] and status < 400:
        status, value = _follow(client, value, wait - body["wait"])
    return status, value


def cmd_keygen(args) -> int:
    key_path = Path(args.key or DEFAULT_DIR / "key.pem")
    if key_path.exists() and not args.force:
        private = load_private_key(key_path.read_text("ascii"))
    else:
        pem = generate_private_pem()
        _write_private(key_path, pem)
        private = load_private_key(pem)
    print(json.dumps({"ok": True, "private_key": str(key_path),
                      "public_key": public_pem_from_private(private)}, ensure_ascii=False, indent=2))
    return 0


def cmd_connect(args) -> int:
    bundle = args.bundle
    if bundle == "-":
        bundle = sys.stdin.read()
    key_path = Path(args.key) if args.key else DEFAULT_DIR / "key.pem"
    private_pem = key_path.read_text("ascii") if key_path.exists() else None
    payload = open_bundle(bundle, private_pem)
    if not {"url", "token"} <= set(payload):
        return _fail("invalid_bundle", "url과 token이 없는 연결 정보입니다")
    path = _config_path(args)
    _write_private(path, json.dumps(payload, ensure_ascii=False, indent=2))
    status, hello = Client(payload).request("GET", "/v1/hello")
    summary = {"ok": status == 200, "saved": str(path), "url": payload["url"], "http_status": status}
    if status == 200:
        summary.update({"mac": hello.get("host"), "device": hello.get("device"), "agents": hello.get("agents")})
    else:
        summary["error"] = hello.get("error")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if status == 200 else 1


def cmd_simple(path: str):
    def run(args) -> int:
        status, value = Client(_load_config(args)).request("GET", path)
        if path == "/v1/guide" and status == 200 and not args.json:
            print(value.get("guide", ""))
            return 0
        return _emit(status, value)
    return run


def cmd_run(args) -> int:
    body = {"command": args.command, "cwd": mac_path(args.cwd), "timeout": args.timeout, "request_id": args.id}
    status, value = _submit(Client(_load_config(args)), "/v1/run", {k: v for k, v in body.items() if v is not None}, args.wait)
    return _emit(status, value)


def cmd_ask(args) -> int:
    prompt = sys.stdin.read() if args.prompt == "-" else args.prompt
    body = {"prompt": prompt, "agent": args.agent, "mode": args.mode, "model": args.model,
            "cwd": mac_path(args.cwd), "timeout": args.timeout, "request_id": args.id}
    status, value = _submit(Client(_load_config(args)), "/v1/ask", {k: v for k, v in body.items() if v is not None}, args.wait)
    return _emit(status, value)


def cmd_job(args) -> int:
    client = Client(_load_config(args))
    status, value = client.request("GET", "/v1/jobs/" + args.job_id, query={"wait": min(50, int(args.wait))})
    if args.wait > 50 and status == 200:
        status, value = _follow(client, value, args.wait - 50)
    return _emit(status, value)


def cmd_jobs(args) -> int:
    status, value = Client(_load_config(args)).request("GET", "/v1/jobs", query={"limit": args.limit, "state": args.state})
    return _emit(status, value)


def cmd_output(args) -> int:
    status, value = Client(_load_config(args)).request(
        "GET", "/v1/jobs/%s/output" % args.job_id,
        query={"stream": args.stream, "offset": args.offset, "limit": args.limit})
    return _emit(status, value)


def cmd_cancel(args) -> int:
    status, value = Client(_load_config(args)).request("POST", "/v1/jobs/%s/cancel" % args.job_id, body={})
    return _emit(status, value)


def cmd_ls(args) -> int:
    status, value = Client(_load_config(args)).request("GET", "/v1/files", query={"path": mac_path(args.path)})
    return _emit(status, value)


def cmd_cat(args) -> int:
    status, value = Client(_load_config(args)).request(
        "GET", "/v1/files", query={"path": mac_path(args.path), "offset": args.offset, "limit": args.limit})
    if status == 200 and args.out and value.get("file"):
        info = value["file"]
        data = base64.b64decode(info["content"]) if info["encoding"] == "base64" else info["content"].encode("utf-8")
        Path(args.out).write_bytes(data)
        info["content"] = "(saved to %s)" % args.out
    return _emit(status, value)


def cmd_put(args) -> int:
    body = {"path": mac_path(args.path), "create_dirs": args.mkdir}
    if args.file:
        body["content_base64"] = base64.b64encode(Path(args.file).read_bytes()).decode("ascii")
    elif args.text is not None:
        body["content"] = args.text
    else:
        body["content"] = sys.stdin.read()
    if args.expect:
        body["expected_sha256"] = args.expect
    status, value = Client(_load_config(args)).request("PUT", "/v1/files", body=body)
    return _emit(status, value)


def cmd_update(args) -> int:
    status, value = Client(_load_config(args)).request("GET", "/v1/client")
    if status != 200 or "source" not in value:
        return _emit(status, value)
    target = Path(args.target or __file__)
    target.write_text(value["source"], "utf-8")
    print(json.dumps({"ok": True, "updated": str(target), "version": value.get("version")}, ensure_ascii=False, indent=2))
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="pn.py", description="pickle-network client")
    root.add_argument("--config", help="연결 설정 파일 (기본 ~/.pickle-network-client/config.json)")
    sub = root.add_subparsers(dest="command_name", required=True)

    p = sub.add_parser("keygen", help="RSA 키 생성 후 공개키 출력")
    p.add_argument("--key")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_keygen)

    p = sub.add_parser("connect", help="맥에서 받은 연결 정보 저장")
    p.add_argument("bundle", help="pn1. 또는 pn1e. 로 시작하는 문자열, - 이면 표준입력")
    p.add_argument("--key", help="개인키 경로 (기본 ~/.pickle-network-client/key.pem)")
    p.set_defaults(func=cmd_connect)

    for name, path in (("hello", "/v1/hello"), ("health", "/v1/health"), ("guide", "/v1/guide")):
        p = sub.add_parser(name)
        p.add_argument("--json", action="store_true")
        p.set_defaults(func=cmd_simple(path))

    p = sub.add_parser("run", help="맥 셸에서 명령 실행")
    p.add_argument("command")
    p.add_argument("--cwd")
    p.add_argument("--timeout", type=int)
    p.add_argument("--wait", type=float, default=120, help="결과를 기다릴 초 (기본 120)")
    p.add_argument("--id", help="재시도용 request_id")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("ask", help="맥에 설치된 AI CLI에 작업 위임")
    p.add_argument("prompt", help="지시문, - 이면 표준입력")
    p.add_argument("--agent", default="auto", help="auto, claude, codex, gemini, agy")
    p.add_argument("--mode", default="edit", choices=("read", "edit", "full"))
    p.add_argument("--model")
    p.add_argument("--cwd")
    p.add_argument("--timeout", type=int)
    p.add_argument("--wait", type=float, default=600)
    p.add_argument("--id")
    p.set_defaults(func=cmd_ask)

    p = sub.add_parser("job", help="작업 상태와 결과")
    p.add_argument("job_id")
    p.add_argument("--wait", type=float, default=0)
    p.set_defaults(func=cmd_job)

    p = sub.add_parser("jobs", help="최근 작업 목록")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--state")
    p.set_defaults(func=cmd_jobs)

    p = sub.add_parser("output", help="작업 출력 이어 읽기")
    p.add_argument("job_id")
    p.add_argument("--stream", default="stdout", choices=("stdout", "stderr"))
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--limit", type=int, default=65536)
    p.set_defaults(func=cmd_output)

    p = sub.add_parser("cancel", help="작업 취소")
    p.add_argument("job_id")
    p.set_defaults(func=cmd_cancel)

    p = sub.add_parser("ls", help="폴더 목록")
    p.add_argument("path")
    p.set_defaults(func=cmd_ls)

    p = sub.add_parser("cat", help="파일 읽기")
    p.add_argument("path")
    p.add_argument("--offset", type=int)
    p.add_argument("--limit", type=int)
    p.add_argument("--out", help="받은 내용을 로컬 파일로 저장")
    p.set_defaults(func=cmd_cat)

    p = sub.add_parser("put", help="파일 쓰기")
    p.add_argument("path")
    p.add_argument("--text")
    p.add_argument("--file", help="보낼 로컬 파일")
    p.add_argument("--mkdir", action="store_true", help="상위 폴더 생성")
    p.add_argument("--expect", help="덮어쓸 파일의 현재 sha256")
    p.set_defaults(func=cmd_put)

    p = sub.add_parser("update", help="맥 서버와 같은 버전으로 이 파일 갱신")
    p.add_argument("--target")
    p.set_defaults(func=cmd_update)
    return root


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        return args.func(args)
    except (OSError, ValueError, KeyError) as exc:
        return _fail("client_error", "%s: %s" % (type(exc).__name__, exc))


if __name__ == "__main__":
    sys.exit(main())
