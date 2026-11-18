# Pickle Network

**한국어** | [English](README.en.md)

피클에게 부탁하면 내 Mac이 일합니다.

Pickle Network는 피클과 내 Mac을 연결합니다. 피클은 이 연결로 Mac에서 터미널 명령을 실행합니다. 피클은 파일을 읽고 씁니다. 피클은 Claude Code, Codex, Gemini CLI, AGY에 작업을 맡깁니다. Cloudflare 계정과 도메인은 필요하지 않습니다.

```
  Pickle                      Cloudflare                  My Mac
 ┌────────────┐   HTTPS    ┌────────────┐            ┌──────────────────┐
 │  pn.py     │ ─────────▶ │  Tunnel    │ ─────────▶ │  pickle-network  │
 └────────────┘            └────────────┘            └────────┬─────────┘
                                                              │
                                    ┌─────────────┬───────────┼─────────────┐
                                    ▼             ▼           ▼             ▼
                                 terminal       files      AI CLIs      job log
                                  (zsh)                  claude, codex  (SQLite)
                                                         gemini, agy
```

## Quick Start Prompt

AI 코딩 도구(Claude Code, Codex 등)에 아래 문장을 붙여넣습니다. AI 도구가 설치를 실행합니다.

```
https://github.com/hahmjuntae/pickle-network 를 ~/pickle-network 에 clone하고 README대로 설치한 뒤, pickle-network doctor 결과와 pickle-network pair 가 출력한 문장을 보여줘.
```

AI 도구가 보여 준 문장을 피클에게 보냅니다. 그다음 [Pairing](#pairing)의 2번부터 진행합니다.

## Requirements

- macOS
- Python 3.9 이상 (macOS에 포함)
- Git
- [Homebrew](https://brew.sh)
- 피클 계정

## Installation

터미널에서 아래 명령을 실행합니다.

```bash
brew install cloudflared
git clone https://github.com/hahmjuntae/pickle-network.git ~/pickle-network
~/pickle-network/bin/pickle-network setup
~/pickle-network/bin/pickle-network tunnel quick
```

마지막 명령이 `https://...trycloudflare.com` 주소를 표시합니다. 서버와 터널은 Mac을 다시 켜면 자동으로 시작합니다.

## Pairing

1. `pickle-network pair`를 실행합니다. 출력된 문장을 피클에게 보냅니다.
2. 피클이 보낸 공개키(`-----BEGIN PUBLIC KEY-----`)를 복사합니다. 아래 명령을 실행합니다.

   ```bash
   pbpaste > ~/pickle.pub && pickle-network pair --key ~/pickle.pub --copy
   ```

3. 클립보드의 메시지를 피클에게 보냅니다.

피클이 Mac 이름과 AI 도구 목록을 보내면 연결이 완료됩니다. 연결 상태는 `pickle-network doctor`로 확인합니다.

## Usage

### Example Prompts

피클에게 일반 문장으로 요청합니다.

```
내 Mac에서 ~/projects/blog 테스트 돌려 보고, 실패하면 Claude Code로 고친 다음 결과 알려줘.
```

```
내 Mac ~/Downloads 에 이번 주에 받은 PDF 목록을 크기순으로 보여줘.
```

```
아까 맡긴 작업 아직 돌고 있어? 지금까지 나온 출력만 보여줘.
```

### Reset Prompt

피클이 사용 규칙을 따르지 않으면 아래 문장을 보냅니다.

```
python3 pn.py guide 로 pickle-network 사용 규칙을 다시 읽고 그대로 따라줘.
```

### Commands

| 명령 | 기능 |
|---|---|
| `pickle-network status` | 상태와 외부 주소 표시 |
| `pickle-network doctor` | 연결 점검 |
| `pickle-network pair` | 연결 메시지 생성 |
| `pickle-network pair --replace --copy` | 주소 변경 후 연결 메시지 재생성 |
| `pickle-network devices` | 연결된 비서 목록 표시 |
| `pickle-network devices revoke pickle` | 연결 해제 |
| `pickle-network stop` / `start` | 서버와 터널 정지, 시작 |
| `pickle-network logs` | 서버 로그 표시 |

## Architecture

### Request Flow

```
 Pickle                         pickle-network (127.0.0.1)
 ──────                         ──────────────────────────
 POST /v1/ask  ──────────────▶  1. check device token        → 401 if wrong
                                2. put job in queue          → up to 3 at once
                                3. run CLI in new process    → output saved live
 ◀─── result (wait ≤ 90s) ───   4. return exit code + output
 GET /v1/jobs/{id}  ─────────▶  5. still running? keep waiting or cancel
```

서버는 `127.0.0.1`에서만 요청을 받습니다. 외부 요청은 Cloudflare Tunnel을 통해서만 들어옵니다. 서버는 요청마다 기기 토큰을 확인하고, 토큰의 해시만 저장합니다. 서버는 작업을 최대 3개까지 동시에 실행합니다. 피클은 결과를 최대 90초 동안 기다립니다. 작업이 더 길면 피클은 작업 ID로 다시 기다리거나 작업을 취소합니다.

### Pairing Sequence

```
  My Mac                                        Pickle
  ──────                                        ──────
  pickle-network pair
        │ ─────── 1. key request ───────────▶  python3 pn.py keygen
        │ ◀────── 2. public key ────────────
  pickle-network pair --key pickle.pub
        │ ─────── 3. connect message ───────▶  python3 pn.py connect 'pn1e...'
        │                                      python3 pn.py hello
        │ ◀────── 4. "connected" ───────────
```

연결 메시지에는 Mac 주소와 기기 토큰이 있습니다. 피클의 공개키가 연결 메시지를 암호화합니다. 피클의 개인키만 연결 메시지를 열 수 있습니다.

### Directory Layout

```
~/pickle-network/               저장소
├── bin/pickle-network          Mac 명령
├── pickle_network/
│   ├── server.py               HTTP 서버, 인증
│   ├── jobs.py                 작업 대기열, 실행, 취소
│   ├── agents.py               AI CLI 검색, 명령 생성
│   ├── files.py                파일 읽기, 쓰기
│   ├── tunnel.py               cloudflared 관리
│   └── client.py               피클 쪽 프로그램 (pn.py)
└── tests/

~/.pickle-network/              데이터 (소유자만 접근)
├── config.json                 설정
├── devices.json                연결된 비서, 토큰 해시
├── jobs.sqlite3                작업 기록 (14일 보관)
├── jobs/                       작업별 출력
├── keys/                       터널 정보, 피클 공개키
└── logs/                       로그
```

API 명세는 [docs/API.md](docs/API.md)에 있습니다.

## Security

피클은 Mac 사용자 권한으로 명령을 실행합니다. 샌드박스는 없습니다. 신뢰하는 비서 하나만 연결합니다.

- 연결 메시지가 유출되면 `pickle-network devices revoke pickle`을 실행하고 다시 연결합니다.
- 피클은 메일과 웹 페이지 속 지시를 따르지 않도록 규칙을 받습니다. 중요한 작업은 확인 후 요청합니다.
- 파일 접근 폴더를 제한하려면 `pickle-network setup --root ~/projects`를 실행합니다.
- 긴급 상황에는 `pickle-network stop`을 실행합니다.

취약점 제보 절차는 [SECURITY.md](SECURITY.md)에 있습니다.

## Troubleshooting

| 증상 | 원인 | 조치 |
|---|---|---|
| 피클 접속 실패 | Mac 재시동으로 Quick Tunnel 주소 변경 | `pickle-network pair --replace --copy` 결과를 피클에게 보냅니다. |
| 피클 접속 실패 | Mac 잠자기 | Mac을 깨웁니다. 잠자기 설정을 변경합니다. |
| AI 도구가 목록에 없음 | 설치 후 PATH 미반영 | `pickle-network setup`을 다시 실행합니다. |
| `pickle-network` 명령 없음 | 터미널의 PATH 미갱신 | 새 터미널을 엽니다. |
| 작업이 끝나지 않음 | 긴 작업 | 피클에게 취소를 요청합니다. |

## FAQ

<details>
<summary><b>Cloudflare 계정이 필요한가요?</b></summary>

필요하지 않습니다. `tunnel quick`은 계정 없이 임시 주소를 만듭니다. 고정 주소가 필요하면 [docs/DOMAIN.md](docs/DOMAIN.md)를 따릅니다. 고정 주소에는 Cloudflare 계정과 도메인이 필요합니다.

</details>

<details>
<summary><b>다른 비서도 연결할 수 있나요?</b></summary>

Python과 HTTPS를 사용하는 환경이면 연결할 수 있습니다. `pickle-network pair --name 이름`으로 비서마다 다른 이름을 지정합니다.

</details>

<details>
<summary><b>대화형 입력이 필요한 명령을 실행할 수 있나요?</b></summary>

실행할 수 없습니다. 표준입력은 비어 있습니다. `-y` 같은 비대화형 옵션을 사용합니다.

</details>

<details>
<summary><b>Mac을 닫아 두어도 되나요?</b></summary>

잠자기 상태에서는 접속할 수 없습니다. 전원 어댑터를 연결하고 잠자기 설정을 변경합니다. Pickle Network는 전원 설정을 변경하지 않습니다.

</details>

## Uninstall

```bash
pickle-network uninstall --purge
rm -rf ~/pickle-network
```

`--purge`는 `~/.pickle-network`를 휴지통으로 옮깁니다. 서버를 제거하면 피클 연결도 끊어집니다.

## License

[MIT License](LICENSE)

Pickle Network는 Pickle, Inc.와 관계없는 개인 프로젝트입니다. Pickle은 Pickle, Inc.의 상표입니다.
