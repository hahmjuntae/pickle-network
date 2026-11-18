# Pickle Network

**한국어** | [English](README.en.md)

피클에게 부탁하면 내 맥이 일합니다.

---

## 1. Overview

### 1.1 Purpose

이 문서는 Pickle Network 설치와 피클 연결 절차를 설명합니다.

### 1.2 Scope

피클은 Pickle Network로 맥에서 다음 작업을 합니다.

| 작업 | 예 |
|---|---|
| 터미널 명령 실행 | 테스트, 빌드, 파일 정리 |
| 파일 읽기, 쓰기 | 문서 확인, 메모 저장 |
| AI 도구에 작업 위임 | Claude Code, Codex, Gemini CLI, AGY |
| 작업 관리 | 진행 확인, 출력 확인, 취소 |

### 1.3 System Diagram

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

---

## 2. Quick Start Prompt

AI 코딩 도구(Claude Code, Codex 등)에 아래 문장을 붙여넣습니다. AI 도구가 [4. Installation](#4-installation)을 실행합니다.

```
https://github.com/hahmjuntae/pickle-network 를 ~/pickle-network 에 clone하고 README대로 설치한 뒤, pickle-network doctor 결과와 pickle-network pair 가 출력한 문장을 보여줘.
```

AI 도구가 보여 준 문장을 피클에게 보냅니다. 그다음 [5. Pairing](#5-pairing)의 5.2를 진행합니다.

---

## 3. Requirements

| 항목 | 조건 | 확인 명령 |
|---|---|---|
| macOS | 로그인한 상태 | `sw_vers` |
| Python | 3.9 이상 (macOS에 포함) | `python3 --version` |
| Git | 모든 버전 | `git --version` |
| Homebrew | 모든 버전 | `brew --version` |
| 피클 | 대화 가능한 계정 | 피클 앱 |

Cloudflare 계정과 도메인은 필요하지 않습니다.

---

## 4. Installation

터미널에서 아래 명령을 순서대로 실행합니다.

### 4.1 Install cloudflared

```bash
brew install cloudflared
```

### 4.2 Download

```bash
git clone https://github.com/hahmjuntae/pickle-network.git ~/pickle-network
```

### 4.3 Set Up the Server

```bash
~/pickle-network/bin/pickle-network setup
```

### 4.4 Open the Tunnel

```bash
~/pickle-network/bin/pickle-network tunnel quick
```

서버와 터널은 맥을 다시 켜면 자동으로 시작합니다.

---

## 5. Pairing

### 5.1 Request a Key

1. 아래 명령을 실행합니다.

   ```bash
   pickle-network pair
   ```

2. 출력된 문장을 피클에게 보냅니다.
3. 피클이 공개키(`-----BEGIN PUBLIC KEY-----`)를 보낼 때까지 기다립니다.

### 5.2 Create the Connection Message

1. 피클이 보낸 공개키를 처음부터 끝까지 복사합니다.
2. 아래 명령을 실행합니다.

   ```bash
   pbpaste > ~/pickle.pub && pickle-network pair --key ~/pickle.pub --copy
   ```

### 5.3 Send the Connection Message

1. 클립보드의 메시지를 피클에게 보냅니다.
2. 피클이 맥 이름과 AI 도구 목록을 보내면 연결이 완료됩니다.

---

## 6. Verification

```bash
pickle-network doctor
```

모든 줄이 `[OK  ]`이면 정상입니다. `[FAIL]` 줄이 있으면 [10. Troubleshooting](#10-troubleshooting)을 확인합니다.

---

## 7. Usage

### 7.1 Example Prompts

피클에게 일반 문장으로 요청합니다.

```
내 맥에서 ~/projects/blog 테스트 돌려 보고, 실패하면 Claude Code로 고친 다음 결과 알려줘.
```

```
내 맥 ~/Downloads 에 이번 주에 받은 PDF 목록을 크기순으로 보여줘.
```

```
아까 맡긴 작업 아직 돌고 있어? 지금까지 나온 출력만 보여줘.
```

### 7.2 Reset Prompt

피클이 사용 규칙을 따르지 않으면 아래 문장을 보냅니다.

```
python3 pn.py guide 로 pickle-network 사용 규칙을 다시 읽고 그대로 따라줘.
```

### 7.3 Commands

| 명령 | 기능 |
|---|---|
| `pickle-network status` | 상태와 외부 주소 표시 |
| `pickle-network doctor` | 연결 점검 |
| `pickle-network pair` | 연결 메시지 생성 |
| `pickle-network pair --replace --copy` | 주소 변경 후 연결 메시지 재생성 |
| `pickle-network devices` | 연결된 비서 목록 표시 |
| `pickle-network devices revoke pickle` | 연결 해제 |
| `pickle-network stop` | 서버와 터널 정지 |
| `pickle-network start` | 서버와 터널 시작 |
| `pickle-network logs` | 서버 로그 표시 |

---

## 8. Architecture

### 8.1 Request Flow

```
 Pickle                         pickle-network (127.0.0.1)
 ──────                         ──────────────────────────
 POST /v1/ask  ──────────────▶  1. check device token        → 401 if wrong
                                2. put job in queue          → up to 3 at once
                                3. run CLI in new process    → output saved live
 ◀─── result (wait ≤ 90s) ───   4. return exit code + output
 GET /v1/jobs/{id}  ─────────▶  5. still running? keep waiting or cancel
```

1. 서버는 `127.0.0.1`에서만 요청을 받습니다.
2. 외부 요청은 Cloudflare Tunnel을 통해서만 들어옵니다.
3. 서버는 요청마다 기기 토큰을 확인합니다.
4. 서버는 토큰의 해시만 저장합니다.
5. 서버는 작업을 최대 3개까지 동시에 실행합니다.
6. 서버는 실행 중에도 출력을 파일에 기록합니다.
7. 피클은 결과를 최대 90초 동안 기다립니다. 작업이 더 길면 작업 ID로 다시 기다리거나 취소합니다.

### 8.2 Pairing Sequence

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

연결 메시지에는 맥 주소와 기기 토큰이 있습니다. 피클의 공개키가 연결 메시지를 암호화합니다. 피클의 개인키만 연결 메시지를 열 수 있습니다.

### 8.3 Directory Layout

```
~/pickle-network/               저장소
├── bin/pickle-network          맥 명령
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

---

## 9. Security

| 위험 | 대응 |
|---|---|
| 피클이 사용자 권한으로 명령 실행 | 신뢰하는 비서 하나만 연결합니다. 샌드박스는 없습니다. |
| 연결 메시지 유출 | `pickle-network devices revoke pickle`을 실행합니다. 그다음 다시 연결합니다. |
| 메일, 웹 페이지 속 지시 | 피클은 이 지시를 따르지 않도록 규칙을 받습니다. 중요한 작업은 확인 후 요청합니다. |
| 넓은 파일 범위 | `pickle-network setup --root ~/projects`로 파일 접근 폴더를 제한합니다. |
| 긴급 상황 | `pickle-network stop`을 실행합니다. |

취약점 제보 절차는 [SECURITY.md](SECURITY.md)에 있습니다.

---

## 10. Troubleshooting

| 증상 | 원인 | 조치 |
|---|---|---|
| 피클 접속 실패 | 맥 재시동으로 Quick Tunnel 주소 변경 | `pickle-network pair --replace --copy`를 실행합니다. 결과를 피클에게 보냅니다. |
| 피클 접속 실패 | 맥 잠자기 | 맥을 깨웁니다. 잠자기 설정을 변경합니다. |
| AI 도구가 목록에 없음 | 설치 후 PATH 미반영 | `pickle-network setup`을 다시 실행합니다. |
| `pickle-network` 명령 없음 | 터미널의 PATH 미갱신 | 새 터미널을 엽니다. |
| 작업이 끝나지 않음 | 긴 작업 | 피클에게 취소를 요청합니다. |

---

## 11. FAQ

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
<summary><b>맥을 닫아 두어도 되나요?</b></summary>

잠자기 상태에서는 접속할 수 없습니다. 전원 어댑터를 연결하고 잠자기 설정을 변경합니다. Pickle Network는 전원 설정을 변경하지 않습니다.

</details>

---

## 12. Uninstall

```bash
pickle-network uninstall --purge
rm -rf ~/pickle-network
```

`--purge`는 `~/.pickle-network`를 휴지통으로 옮깁니다. 서버를 제거하면 피클 연결도 끊어집니다.

---

## 13. License

[MIT License](LICENSE)

Pickle Network는 Pickle, Inc.와 관계없는 개인 프로젝트입니다. Pickle은 Pickle, Inc.의 상표입니다.
