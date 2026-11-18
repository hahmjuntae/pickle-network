# Pickle Network

피클에게 부탁하면 내 맥이 대신 일합니다.

pickle-network는 피클(Pickle) 비서와 내 맥을 이어 주는 작은 서버입니다. 연결된 피클은 맥에서 터미널 명령을 실행하고, 파일을 읽고 쓰고, Claude Code·Codex·Gemini CLI에 일을 맡길 수 있습니다. 계정 가입이나 도메인은 필요 없습니다.

Claude Code, Codex 같은 AI 코딩 도구에 아래 한 줄을 붙여넣으면 설치부터 연결 준비까지 알아서 합니다.

```
https://github.com/hahmjuntae/pickle-network 를 ~/pickle-network 에 clone하고 README대로 설치한 뒤, pickle-network doctor 결과와 pickle-network pair 가 출력한 문장을 보여줘.
```

출력된 문장을 피클에게 보내고 [피클 연결](#피클-연결) 2단계부터 이어 가면 됩니다.

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


## 설치

macOS와 [Homebrew](https://brew.sh)가 있으면 됩니다. 터미널에 붙여넣으세요.

```bash
brew install cloudflared
git clone https://github.com/hahmjuntae/pickle-network.git ~/pickle-network
~/pickle-network/bin/pickle-network setup
~/pickle-network/bin/pickle-network tunnel quick
```

마지막 줄에 `https://...trycloudflare.com` 주소가 나오면 끝입니다. 맥을 다시 켜도 자동으로 실행됩니다.


## 피클 연결

메시지를 두 번 주고받으면 연결됩니다.

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

1. `pickle-network pair`를 실행하고, 나온 문장을 피클에게 보냅니다.
2. 피클이 보내 준 공개키(`-----BEGIN PUBLIC KEY-----`부터 끝까지)를 복사하고 실행합니다.

   ```bash
   pbpaste > ~/pickle.pub && pickle-network pair --key ~/pickle.pub --copy
   ```

3. 클립보드에 담긴 연결 메시지를 피클에게 보냅니다.

피클이 맥 이름과 AI 도구 목록을 알려 주면 연결된 것입니다.


## 사용

피클에게 평소처럼 부탁하면 됩니다.

```
내 맥에서 ~/projects/blog 테스트 돌려 보고, 실패하면 Claude Code로 고친 다음 결과 알려줘.

내 맥 ~/Downloads 에 이번 주에 받은 PDF 목록을 크기순으로 보여줘.

아까 맡긴 작업 아직 돌고 있어? 지금까지 나온 출력만 보여줘.
```


## 구조

### 요청 하나가 처리되는 과정

```
 Pickle                         pickle-network (127.0.0.1)
 ──────                         ──────────────────────────
 POST /v1/ask  ──────────────▶  1. check device token        → 401 if wrong
                                2. put job in queue          → up to 3 at once
                                3. run CLI in new process    → output saved live
 ◀─── result (wait ≤ 90s) ───   4. return exit code + output
 GET /v1/jobs/{id}  ─────────▶  5. still running? keep waiting or cancel
```

1. 서버는 맥 안(`127.0.0.1`)에서만 열립니다. 바깥 요청은 Cloudflare Tunnel을 거쳐서만 들어옵니다.
2. 요청마다 기기 토큰을 확인합니다. 서버에는 토큰의 해시만 저장합니다.
3. 작업은 최대 3개까지 동시에 실행되고, 출력은 실행 중에도 파일에 쌓입니다.
4. 피클은 최대 90초씩 결과를 기다리고, 더 걸리면 작업 ID로 이어서 기다리거나 취소합니다.

### 연결 메시지 보호

연결 메시지에는 맥 주소와 기기 토큰이 들어 있습니다. 이 내용은 피클이 만든 공개키로 암호화되므로, 대화 기록에 남아도 피클의 개인키가 없으면 열 수 없습니다.

### 파일 구성

```
pickle-network/                 저장소
├── bin/pickle-network          맥에서 쓰는 명령
├── pickle_network/
│   ├── server.py               HTTP 서버, 인증
│   ├── jobs.py                 작업 대기열, 실행, 취소
│   ├── agents.py               AI CLI 찾기, 명령 만들기
│   ├── files.py                파일 읽기, 쓰기
│   ├── tunnel.py               cloudflared 관리
│   └── client.py               피클 쪽 프로그램 (pn.py)
└── tests/

~/.pickle-network/              내 맥의 데이터 (본인만 읽기 가능)
├── config.json                 설정
├── devices.json                연결된 비서와 토큰 해시
├── jobs.sqlite3                작업 기록 (14일 보관)
├── jobs/                       작업별 출력
├── keys/                       터널 정보, 피클 공개키
└── logs/                       로그
```


## 명령어

```
pickle-network status                  상태와 외부 주소
pickle-network doctor                  연결 점검
pickle-network pair                    피클 연결 메시지 만들기
pickle-network pair --replace --copy   주소가 바뀌었을 때 다시 만들기
pickle-network devices                 연결된 비서 목록
pickle-network devices revoke pickle   연결 끊기
pickle-network stop / start            멈추기, 다시 켜기
pickle-network uninstall --purge       완전히 지우기
```


## 질문과 답

<details>
<summary><b>Cloudflare 계정이 필요한가요?</b></summary>

아니요. `tunnel quick`은 계정 없이 임시 주소를 만듭니다. 주소를 고정하고 싶을 때만 [내 도메인으로 연결하기](docs/DOMAIN.md)를 따르세요.

</details>

<details>
<summary><b>피클이 갑자기 접속을 못 해요.</b></summary>

임시 주소는 맥을 재시동하면 바뀝니다. 아래 명령의 결과를 피클에게 다시 보내 주세요. 맥이 잠자기 상태여도 접속할 수 없습니다.

```bash
pickle-network pair --replace --copy
```

</details>

<details>
<summary><b>안전한가요?</b></summary>

연결된 피클은 내 맥에서 나와 같은 권한으로 움직입니다. 내 비서 하나만 연결하고, 이상하면 `pickle-network stop`으로 바로 멈추세요. 파일 범위를 줄이려면 `pickle-network setup --root ~/projects`처럼 폴더를 지정합니다.

</details>


MIT License. Pickle, Inc.와 관계없는 개인 프로젝트입니다.
