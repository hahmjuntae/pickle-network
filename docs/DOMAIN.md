# 내 도메인으로 연결하기

Quick Tunnel 대신 `mac.example.com` 같은 고정 주소를 쓰는 방법입니다. 주소가 바뀌지 않고, Cloudflare Access가 한 번 더 막아 줍니다.

필요한 것은 Cloudflare 계정과 Cloudflare에 연결한 도메인입니다. 아래 메뉴 이름은 Cloudflare 화면이 바뀌면 조금 다를 수 있습니다.

## 1. 터널 만들기

1. Cloudflare Zero Trust 대시보드에서 **Networks → Tunnels → Create a tunnel**을 누르고 `cloudflared` 유형으로 만듭니다.
2. 설치 안내에 나오는 긴 토큰 문자열을 복사한 뒤 저장합니다.

   ```bash
   pbpaste > ~/tunnel-token
   ```

3. **Public hostname**에 `mac.example.com`을 추가하고, 서비스 주소는 `http://127.0.0.1:7979`로 적습니다.

## 2. Access로 잠그기

1. **Access → Service credentials → Service tokens**에서 토큰을 만들고 Client ID와 Client Secret을 받습니다. Secret을 복사한 뒤 저장합니다.

   ```bash
   pbpaste > ~/access-secret
   ```

2. **Access → Applications**에서 `mac.example.com`용 Self-hosted 앱을 만들고, 정책 Action은 `Service Auth`, 대상은 방금 만든 서비스 토큰으로 지정합니다.

## 3. 맥에 등록하기

`--access-expires`에는 서비스 토큰 만료 시각을 넣습니다. 만료 7일 전부터 `doctor`가 알려 줍니다.

```bash
pickle-network tunnel token \
  --token-file ~/tunnel-token \
  --hostname mac.example.com \
  --access-id 0123abcd.access \
  --access-secret-file ~/access-secret \
  --access-expires 2027-01-31T00:00:00Z
```

```bash
rm ~/tunnel-token ~/access-secret
```

```bash
pickle-network doctor
```

모든 줄이 `OK`면 `pickle-network pair --replace` 결과를 피클에게 보내 주세요.
