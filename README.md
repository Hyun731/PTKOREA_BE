# PTK 백엔드

리서치 팩트북 API 서버입니다. 구성은 아래와 같습니다.
- API: FastAPI `/v1`
- 계산·장표 엔진: `core/`
- PPTX 렌더러와 미리보기: LibreOffice
- 외부 연동: Perplexity, Anthropic, ScrapeCreators, Apify

웹 화면은 별도 저장소(PTKOREA_FE)에 있습니다.

## 도커로 실행 (권장)

```bash
cp .env.example .env
```

`.env`에 API 키와 `BACKEND_TOKEN`을 채웁니다. 토큰은 아래 명령으로 만듭니다.

```bash
openssl rand -hex 32
```

```bash
docker compose up -d --build
```

- 주소: `http://127.0.0.1:8000`
  - 헬스체크: `GET /healthz`
  - API: `/v1/*`
- 데이터: `./var`를 컨테이너의 `/app/var`에 연결합니다. 여기에 SQLite DB, 업로드 파일, 출력물이 남습니다. DB 마이그레이션은 시작할 때 자동으로 적용됩니다.
- PPTX 미리보기는 컨테이너 안의 LibreOffice로 렌더링합니다. 이미지에 Pretendard와 Noto Sans KR 글꼴이 들어 있습니다.
- `BACKEND_TOKEN`을 설정하면 `/healthz`를 뺀 모든 요청에 `X-Backend-Token` 헤더가 필요합니다. 웹 서버가 이 헤더를 붙여 보냅니다.

로그 보기와 중지:

```bash
docker compose logs -f api
```

```bash
docker compose down
```

## 외부에 열기 (Vercel 프런트와 연결)

ngrok 고정 도메인을 compose 서비스로 띄웁니다. 백엔드와 함께 켜지고, 꺼져도 다시 살아납니다.

1. `.env`에 두 값을 넣습니다.
   ```
   NGROK_AUTHTOKEN=<ngrok 대시보드의 authtoken>
   NGROK_DOMAIN=<받은 도메인>.ngrok-free.dev
   ```
2. 터널과 함께 실행합니다.
   ```bash
   docker compose --profile tunnel up -d
   ```
3. 외부 주소는 `https://<NGROK_DOMAIN>`입니다. 이 주소를 프런트의 `API_ORIGIN`에 넣습니다.
   - ngrok 요청 상태는 `http://127.0.0.1:4040`에서 볼 수 있습니다.

연결 확인 (토큰 없이 401이 나오면 정상):

```bash
curl -i https://<NGROK_DOMAIN>/v1/meta
```

## 개발 (도커 없이)

```bash
/opt/homebrew/bin/python3.12 -m venv .venv && .venv/bin/pip install -r requirements.lock && .venv/bin/pip install --no-deps -e ".[dev]"
```

```bash
.venv/bin/uvicorn app.main:app --port 8000 --reload
```

```bash
PTK_SKIP_DOTENV=1 .venv/bin/python -m pytest -q
```
