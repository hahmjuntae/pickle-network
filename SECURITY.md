# 보안 정책

pickle-network는 신뢰하는 한 사람이 자기 맥을 원격으로 쓰기 위한 도구입니다. 인증을 통과한 요청은 맥 로그인 사용자 권한으로 실행됩니다. 샌드박스나 다중 사용자 격리를 제공하지 않습니다.

## 제보

인증 우회, 허용 폴더 밖 파일 접근, 토큰이나 연결 정보 노출처럼 설계한 경계를 넘는 문제를 제보 대상으로 봅니다.

1. GitHub 저장소의 **Security → Report a vulnerability**로 비공개 제보합니다.
2. 실제 토큰, 주소, 개인 로그는 공개 이슈에 올리지 않습니다.

## 운영 수칙

| 상황 | 조치 |
|---|---|
| 연결 정보가 새어 나간 것 같음 | `pickle-network devices revoke 이름` 후 `pair --replace`로 다시 연결 |
| 맥을 당장 막아야 함 | `pickle-network stop` |
| Access 서비스 토큰 만료 임박 | Cloudflare에서 기간 연장 후 `tunnel token ... --access-expires`로 새 만료 시각 기록 |
| Quick Tunnel 사용 중 | 시험이 끝나면 `pickle-network tunnel off` |
