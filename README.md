# pickle-network

피클에게 부탁하면 내 맥이 일합니다.

피클(Pickle) 비서가 내 맥에서 터미널 명령을 실행하고, 파일을 읽고 쓰고, Claude Code·Codex·Gemini CLI 같은 AI 도구에 일을 맡길 수 있게 연결해 줍니다. 계정 가입이나 도메인은 필요 없습니다.

[![tests](https://github.com/hahmjuntae/pickle-network/actions/workflows/tests.yml/badge.svg)](https://github.com/hahmjuntae/pickle-network/actions/workflows/tests.yml)
[![license](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

> [!WARNING]
> 연결된 피클은 내 맥에서 나와 같은 권한으로 움직입니다. 내 비서 하나만 연결하고, 연결 정보는 비밀번호처럼 다뤄 주세요.

## 준비물

- macOS
- Python 3.9 이상 (macOS 기본 `python3`로 충분합니다)
- [Homebrew](https://brew.sh)

## 1. 맥에 설치하기

터미널에 차례로 붙여넣으세요.

```bash
git clone https://github.com/hahmjuntae/pickle-network.git ~/pickle-network
```

```bash
~/pickle-network/bin/pickle-network setup
```

```bash
brew install cloudflared
```

```bash
pickle-network tunnel quick
```

마지막 명령이 `https://...trycloudflare.com` 주소를 보여 주면 준비가 끝난 것입니다. 맥을 켜면 자동으로 다시 실행됩니다.

> `pickle-network`를 찾을 수 없다고 나오면 터미널을 새로 열어 주세요.

## 2. 피클과 연결하기

피클과 메시지를 두 번 주고받으면 연결됩니다.

1. 아래 명령을 실행하고, 출력된 문장을 피클에게 그대로 보냅니다.

   ```bash
   pickle-network pair
   ```

2. 피클이 `-----BEGIN PUBLIC KEY-----`로 시작하는 공개키를 보내 주면, 그 공개키를 복사한 뒤 아래 두 명령을 실행합니다.

   ```bash
   pbpaste > ~/pickle.pub
   ```

   ```bash
   pickle-network pair --key ~/pickle.pub --copy
   ```

3. 연결 메시지가 클립보드에 복사돼 있습니다. 피클 대화창에 붙여넣어 보내세요.

피클이 맥 이름과 설치된 AI 도구 목록을 알려 주면 연결된 것입니다.

## 3. 이렇게 부탁하세요

평소처럼 말하면 됩니다.

```text
내 맥에서 ~/projects/blog 테스트 돌려 보고, 실패하면 Claude Code로 고친 다음 결과 알려줘.
```

```text
내 맥 ~/Downloads 에 이번 주에 받은 PDF 목록을 크기순으로 보여줘. 지우지는 마.
```

```text
아까 맡긴 작업 아직 돌고 있어? 지금까지 나온 출력 마지막 부분만 보여줘.
```

피클이 규칙을 잊은 것 같으면 이렇게 보내 주세요.

```text
python3 pn.py guide 로 pickle-network 사용 규칙을 다시 읽고 그대로 따라줘.
```

## 설치를 AI에게 맡기기

Claude Code나 Codex 같은 코딩 에이전트에게 이 문장을 붙여넣으면 1단계를 대신 해 줍니다.

```text
https://github.com/hahmjuntae/pickle-network 를 ~/pickle-network 에 clone하고 README대로 설치해 줘.
setup, cloudflared 설치, tunnel quick 까지 하고 pickle-network doctor 결과를 보여줘.
마지막으로 pickle-network pair 를 실행해서 피클에게 보낼 문장을 알려줘.
```

## 자주 쓰는 명령

| 명령 | 하는 일 |
|---|---|
| `pickle-network status` | 지금 상태와 외부 주소 보기 |
| `pickle-network doctor` | 연결이 잘 되는지 점검 |
| `pickle-network devices` | 연결된 비서 목록 |
| `pickle-network devices revoke pickle` | 그 비서의 연결 끊기 |
| `pickle-network stop` | 급할 때 모두 멈추기 (`start`로 다시 켜기) |
| `pickle-network uninstall --purge` | 완전히 지우기 |

## 알아 두면 좋은 것

- 맥이 잠자기 상태면 피클이 접속할 수 없습니다.
- Quick Tunnel 주소는 맥을 재시동하거나 터널을 다시 켜면 바뀝니다. 주소가 바뀌면 `pickle-network pair --replace` 결과를 피클에게 다시 보내 주세요. 공개키는 저장돼 있어서 다시 받을 필요가 없습니다.
- 주소가 바뀌지 않게 하고 싶다면 [내 도메인으로 연결하기](docs/DOMAIN.md)를 참고하세요. Cloudflare 계정과 도메인이 필요합니다.
- 연결 정보는 피클의 공개키로 암호화해서 보냅니다. 대화 기록에 남아도 피클 말고는 열 수 없습니다.
- 메일이나 웹 페이지에 적힌 지시는 따르지 않도록 피클에게 규칙을 줍니다. 그래도 완벽한 방어는 아니니, 중요한 폴더만 열어 두고 싶다면 `pickle-network setup --root ~/projects`처럼 범위를 좁혀 주세요.

## 문제 해결

| 증상 | 해결 |
|---|---|
| 피클이 접속을 못 함 | `pickle-network doctor`를 실행해 `FAIL` 줄을 확인합니다. 주소가 바뀌었으면 `pair --replace`로 다시 보냅니다. |
| AI 도구가 목록에 없음 | 터미널에서 그 도구가 실행되는지 확인한 뒤 `pickle-network setup`을 다시 실행합니다. |
| 작업이 너무 오래 걸림 | 피클에게 "그 작업 취소해 줘"라고 하면 됩니다. |

## 더 보기

- [API 문서](docs/API.md): 피클 말고 다른 도구에서 직접 호출할 때
- [내 도메인으로 연결하기](docs/DOMAIN.md)
- [개발 안내](docs/DEVELOPMENT.md)
- [보안 정책](SECURITY.md)

Pickle, Inc.와 관계없는 개인 프로젝트입니다. [MIT License](LICENSE)
