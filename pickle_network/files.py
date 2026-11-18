from __future__ import annotations

import base64
import hashlib
import os
import stat
import tempfile
from pathlib import Path

from .jobs import ApiError

MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_ENTRIES = 1000


class Files:
    def __init__(self, roots: list):
        self.roots = [Path(os.path.expanduser(r)).resolve() for r in roots]

    def resolve(self, raw: str, must_exist: bool = True) -> Path:
        if not isinstance(raw, str) or not raw or "\x00" in raw or len(raw) > 4096:
            raise ApiError("invalid_path", "path가 필요합니다")
        candidate = Path(os.path.expanduser(raw))
        if not candidate.is_absolute():
            raise ApiError("invalid_path", "절대 경로나 ~ 경로가 필요합니다")
        if must_exist:
            resolved = candidate.resolve()
        else:
            resolved = candidate.parent.resolve() / candidate.name
            if resolved.is_symlink():
                resolved = resolved.resolve()
        if not any(resolved == root or root in resolved.parents for root in self.roots):
            raise ApiError("path_denied", "허용된 폴더 밖의 경로입니다: " + raw, 403)
        if must_exist and not resolved.exists():
            raise ApiError("not_found", "경로가 없습니다: " + raw, 404)
        return resolved

    def read(self, raw: str, offset: int = 0, limit: int = MAX_FILE_BYTES) -> dict:
        path = self.resolve(raw)
        if path.is_dir():
            return self.listing(path)
        if not path.is_file():
            raise ApiError("not_a_file", "일반 파일이 아닙니다")
        size = path.stat().st_size
        offset = max(0, int(offset))
        limit = max(1, min(int(limit), MAX_FILE_BYTES))
        with open(path, "rb") as source:
            source.seek(offset)
            data = source.read(limit)
        try:
            content, encoding = data.decode("utf-8"), "utf-8"
        except UnicodeDecodeError:
            content, encoding = base64.b64encode(data).decode("ascii"), "base64"
        result = {"type": "file", "path": str(path), "size": size, "offset": offset,
                  "length": len(data), "complete": offset == 0 and len(data) == size,
                  "encoding": encoding, "content": content}
        if result["complete"]:
            result["sha256"] = hashlib.sha256(data).hexdigest()
        return result

    def listing(self, path: Path) -> dict:
        entries = []
        with os.scandir(path) as items:
            for item in items:
                try:
                    info = item.stat(follow_symlinks=False)
                except OSError:
                    continue
                kind = "dir" if stat.S_ISDIR(info.st_mode) else "link" if stat.S_ISLNK(info.st_mode) else "file"
                entries.append({"name": item.name, "type": kind, "size": info.st_size, "modified": info.st_mtime})
        entries.sort(key=lambda e: (e["type"] != "dir", e["name"].lower()))
        return {"type": "dir", "path": str(path), "count": len(entries),
                "truncated": len(entries) > MAX_ENTRIES, "entries": entries[:MAX_ENTRIES]}

    def write(self, body: dict) -> dict:
        allowed = {"path", "content", "content_base64", "expected_sha256", "create_dirs", "if_absent"}
        unknown = set(body) - allowed
        if unknown:
            raise ApiError("invalid_field", "알 수 없는 필드: " + ", ".join(sorted(unknown)))
        if ("content" in body) == ("content_base64" in body):
            raise ApiError("invalid_content", "content와 content_base64 중 하나만 보내세요")
        if "content" in body:
            if not isinstance(body["content"], str):
                raise ApiError("invalid_content", "content는 문자열입니다")
            data = body["content"].encode("utf-8")
        else:
            try:
                data = base64.b64decode(body["content_base64"], validate=True)
            except (ValueError, TypeError):
                raise ApiError("invalid_content", "content_base64가 올바르지 않습니다")
        if len(data) > MAX_FILE_BYTES:
            raise ApiError("too_large", "파일은 %d바이트 이하만 쓸 수 있습니다" % MAX_FILE_BYTES, 413)
        raw = body.get("path")
        candidate = Path(os.path.expanduser(raw)) if isinstance(raw, str) else None
        if body.get("create_dirs") and candidate is not None and candidate.is_absolute():
            parent = self.resolve(str(_nearest_existing(candidate.parent)))
            if parent.is_dir():
                target_parent = parent / candidate.parent.relative_to(_nearest_existing(candidate.parent))
                self.resolve(str(target_parent / candidate.name), must_exist=False)
                target_parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        path = self.resolve(raw, must_exist=False)
        if not path.parent.is_dir():
            raise ApiError("parent_missing", "상위 폴더가 없습니다. create_dirs를 true로 보내세요", 404)
        existed = path.exists()
        if existed and not path.is_file():
            raise ApiError("not_a_file", "일반 파일이 아닌 경로에는 쓸 수 없습니다")
        if body.get("if_absent") and existed:
            raise ApiError("already_exists", "파일이 이미 있습니다", 409)
        expected = body.get("expected_sha256")
        if expected is not None:
            current = hashlib.sha256(path.read_bytes()).hexdigest() if existed else None
            if current != expected:
                raise ApiError("sha256_mismatch", "파일이 그사이 바뀌었습니다", 409)
        mode = path.stat().st_mode & 0o7777 if existed else 0o644
        fd, temp = tempfile.mkstemp(prefix="." + path.name + ".", dir=str(path.parent))
        try:
            os.fchmod(fd, mode)
            with os.fdopen(fd, "wb") as sink:
                sink.write(data)
                sink.flush()
                os.fsync(sink.fileno())
            os.replace(temp, path)
        except BaseException:
            try:
                os.unlink(temp)
            except FileNotFoundError:
                pass
            raise
        return {"path": str(path), "size": len(data), "created": not existed,
                "sha256": hashlib.sha256(data).hexdigest()}


def _nearest_existing(path: Path) -> Path:
    while not path.exists() and path != path.parent:
        path = path.parent
    return path
