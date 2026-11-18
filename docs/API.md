# API

모든 요청에 `Authorization: Bearer pn_<기기ID>_<비밀값>` 헤더가 필요합니다. 도메인 연결이면 Cloudflare Access 헤더 `CF-Access-Client-Id`, `CF-Access-Client-Secret`도 함께 보냅니다. 요청과 응답 본문은 UTF-8 JSON입니다.

## 응답 형식

모든 응답에 `ok`와 `service: "pickle-network"`가 들어 있습니다. 실패하면 `error.code`와 `error.message`를 돌려줍니다.

```json
{"ok": false, "service": "pickle-network", "error": {"code": "invalid_cwd", "message": "존재하는 절대 폴더가 필요합니다: ~/nope"}}
```

401, 403 응답에 `service` 필드가 없으면 맥까지 오지 않고 Cloudflare에서 거절된 요청입니다.

## 엔드포인트

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/v1/hello` | 맥 정보, 연결 기기, 설치된 AI CLI, 제한값 |
| GET | `/v1/guide` | 연결 비서용 사용 규칙(Markdown) |
| GET | `/v1/health` | 작업자 상태, 작업 수, Access 만료 시각 |
| POST | `/v1/run` | 셸 명령 실행 |
| POST | `/v1/ask` | AI CLI에 작업 위임 |
| GET | `/v1/jobs?limit=20&state=running` | 최근 작업 목록 |
| GET | `/v1/jobs/{id}?wait=50` | 작업 상태와 출력. `wait`초까지 완료를 기다림 |
| GET | `/v1/jobs/{id}/output?stream=stdout&offset=0&limit=65536` | 출력 이어 읽기 |
| POST | `/v1/jobs/{id}/cancel` | 작업 취소 |
| GET | `/v1/files?path=~/a.txt` | 파일 읽기 또는 폴더 목록 |
| PUT | `/v1/files` | 파일 쓰기 |
| GET | `/v1/client` | 서버와 같은 버전의 `pn.py` 소스 |

## POST /v1/run

| 필드 | 형식 | 기본값 | 설명 |
|---|---|---|---|
| `command` | 문자열 | 필수 | `zsh -lc`로 실행할 명령 |
| `cwd` | 문자열 | 설정의 `default_cwd` | 절대 경로 또는 `~` 경로 |
| `timeout` | 정수 | 3600 | 1~86400초 |
| `wait` | 숫자 | 0 | 응답 전에 기다릴 초, 최대 90 |
| `request_id` | 문자열 | 없음 | 재시도 키. 같은 값과 같은 본문이면 기존 작업을 돌려줌 |

새 작업이면 202, `request_id`로 기존 작업을 돌려주면 200입니다. 같은 `request_id`에 다른 본문을 보내면 409입니다.

```json
{
  "ok": true,
  "job": {
    "id": "4d948bf0ba4c4e38a061e0633d16afaa",
    "state": "succeeded",
    "exit_code": 0,
    "duration": 0.08,
    "stdout": "hi\n",
    "stdout_complete": true,
    "stderr": "",
    "stderr_complete": true
  },
  "reused": false,
  "poll": "/v1/jobs/4d948bf0ba4c4e38a061e0633d16afaa?wait=50"
}
```

## POST /v1/ask

| 필드 | 형식 | 기본값 | 설명 |
|---|---|---|---|
| `prompt` | 문자열 | 필수 | AI CLI에 전달할 지시 |
| `agent` | 문자열 | `auto` | `auto`, `claude`, `codex`, `gemini`, `agy` |
| `mode` | 문자열 | `edit` | `read`, `edit`, `full` |
| `model` | 문자열 | 없음 | CLI에 넘길 모델 이름 |
| `cwd`, `timeout`, `wait`, `request_id` | | | `/v1/run`과 같음 |

설치되지 않은 CLI를 지정하면 404 `agent_missing`입니다.

## 작업 상태

| `state` | 뜻 |
|---|---|
| `queued` | 대기 중 |
| `running` | 실행 중 |
| `succeeded` | 종료 코드 0 |
| `failed` | 종료 코드가 0이 아님 |
| `timed_out` | 제한 시간 초과로 중단 |
| `canceled` | 취소 요청으로 중단 |
| `interrupted` | 서버 종료나 재시작으로 추적이 끊김. 다시 실행하지 않음 |
| `error` | 프로세스를 시작하지 못함 |

작업 응답의 `stdout`, `stderr`에는 마지막 64KiB가 들어 있습니다. `*_complete`가 `false`면 `/output`으로 처음부터 읽습니다.

## 파일

`GET /v1/files`는 경로가 폴더면 `{"dir": {...}}`, 파일이면 `{"file": {...}}`를 돌려줍니다. UTF-8로 읽히지 않는 파일은 `encoding: "base64"`로 돌려줍니다. 한 번에 최대 8MiB이며 `offset`, `limit`으로 나눠 읽습니다.

`PUT /v1/files` 본문입니다.

| 필드 | 설명 |
|---|---|
| `path` | 쓸 경로 |
| `content` 또는 `content_base64` | 둘 중 하나 |
| `create_dirs` | `true`면 상위 폴더 생성 |
| `if_absent` | `true`면 파일이 있을 때 409 |
| `expected_sha256` | 현재 파일 해시가 다르면 409. 덮어쓰기 충돌 방지 |

파일 API는 `setup --root`로 지정한 폴더(기본 홈 폴더) 안에서만 동작합니다. 심볼릭 링크를 따라간 실제 경로로 판단합니다.

## 오류 코드

| HTTP | `code` | 원인 |
|---|---|---|
| 400 | `invalid_field`, `invalid_command`, `invalid_cwd`, `invalid_timeout` 등 | 요청 값 오류 |
| 401 | `unauthorized` | 기기 토큰 없음, 틀림, 폐기됨 |
| 403 | `browser_denied` | `Origin` 헤더가 있는 요청 |
| 403 | `scope_denied` | 읽기 전용 기기의 쓰기 요청 |
| 403 | `path_denied` | 허용 폴더 밖 경로 |
| 404 | `not_found`, `agent_missing` | 없는 작업, 경로, CLI |
| 409 | `request_id_conflict`, `sha256_mismatch`, `already_exists` | 충돌 |
| 413 | `too_large` | 본문 12MiB 또는 파일 8MiB 초과 |
| 429 | `queue_full`, `too_many_failures` | 대기열 가득, 인증 실패 누적 |
