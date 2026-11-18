# 개발

Python 표준 라이브러리만 씁니다. 외부 패키지를 추가하지 않습니다.

## 시험

```bash
python3 -m unittest discover -s tests -v
```

시험은 임시 폴더에 서버를 띄워 실제 HTTP 요청과 프로세스로 확인합니다. 실제 AI CLI 대신 인자를 출력하는 가짜 `claude` 스크립트를 씁니다.

## 구조

| 파일 | 역할 |
|---|---|
| `pickle_network/cli.py` | `pickle-network` 명령 |
| `pickle_network/server.py` | HTTP 서버, 인증, 라우팅 |
| `pickle_network/jobs.py` | 작업 저장(SQLite), 실행, 출력 기록, 취소 |
| `pickle_network/agents.py` | AI CLI 탐지와 명령 조립 |
| `pickle_network/files.py` | 파일 API와 허용 폴더 검사 |
| `pickle_network/devices.py` | 기기 토큰 발급, 확인, 폐기 |
| `pickle_network/shellenv.py` | 대화형 셸 PATH 수집 |
| `pickle_network/launchd.py` | LaunchAgent 등록 |
| `pickle_network/tunnel.py` | cloudflared 서비스 구성 |
| `pickle_network/guide.py` | 연결 비서용 사용 규칙 |
| `pickle_network/client.py` | 피클 쪽 단일 파일 클라이언트(`pn.py`). 패키지 내부를 import하지 않음 |

## 규칙

1. `client.py`는 다른 모듈을 import하지 않습니다. 파일 하나로 내려받아 실행되기 때문입니다.
2. 연결 정보 묶음 형식(`pn1.`, `pn1e.`)을 바꾸면 접두어 버전을 올립니다.
3. 토큰, Access Secret, 연결 정보는 로그와 응답에 넣지 않습니다.
4. 실패한 작업은 자동으로 다시 실행하지 않습니다.

## 연결 정보 암호화

`pn1e.` 묶음은 다음 순서로 만듭니다.

1. 32바이트 무작위 키 `K`를 RSA-OAEP(SHA-256)로 피클 공개키에 암호화합니다.
2. `HMAC-SHA256(K, "pn-enc")`, `HMAC-SHA256(K, "pn-mac")`으로 암호화 키와 인증 키를 나눕니다.
3. 본문은 HMAC-SHA256 카운터 모드 키스트림과 XOR합니다.
4. `HMAC(인증 키, RSA 암호문 + nonce + 본문)`을 태그로 붙입니다.

RSA-OAEP 구현은 시험에서 `openssl pkeyutl`과 양방향 호환을 확인합니다.
