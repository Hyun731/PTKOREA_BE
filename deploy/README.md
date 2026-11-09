# MADP 배포 (백엔드 + Postgres)

프론트는 Vercel 그대로. 백엔드와 DB만 MADP(OpenStack) 서버 한 대에 올립니다.

```
push/PR ─► ci.yml: pytest
main    ─► deploy.yml: pytest → 이미지 빌드 → ghcr.io/hyun731/ptkorea-be:<sha>
                     └► MADP 서버의 self-hosted runner(label: madp)가 deploy/deploy.sh 실행
                          pull → up -d → alembic upgrade head → /healthz 확인 → 실패 시 이전 이미지로
```

서버로 들어오는 SSH/Teleport 접속은 쓰지 않습니다. 러너가 GitHub로 먼저 연결해 일을 받아 갑니다.
비밀값은 서버의 `/opt/ptk/.env`에만 있고 GitHub에는 올리지 않습니다.

## 1. 서버 준비 (한 번)

권장: Ubuntu 22.04/24.04, vCPU 2 이상, RAM 4GB 이상(LibreOffice), 디스크 40GB 이상. 밖으로 나가는 인터넷이 돼야 합니다.

```bash
# Docker
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu        # 다시 로그인해야 적용

# 배포 폴더와 비밀값
sudo mkdir -p /opt/ptk && sudo chown ubuntu: /opt/ptk
nano /opt/ptk/.env                    # 아래 2번 참고
chmod 600 /opt/ptk/.env
```

## 2. `/opt/ptk/.env`

로컬 `backend/.env`의 키를 그대로 옮기고 아래를 더합니다. `DATABASE_URL`은 넣지 않습니다(compose가 만듦).

```
POSTGRES_PASSWORD=<긴 무작위 문자열>
PTK_PROFILE=tunnel          # tunnel(ngrok 고정 도메인) | https(Caddy, 공인 IP 필요) | 비워 두면 내부 전용
# tunnel일 때
NGROK_AUTHTOKEN=...
NGROK_DOMAIN=...
# https일 때
# DOMAIN=api.example.com
```

ngrok 고정 도메인은 한 번에 한 곳에서만 열 수 있습니다. 서버로 옮길 때 PC의 터널(`docker compose --profile tunnel`)은 먼저 내려 주세요.

## 3. GitHub 러너 등록 (한 번)

PTKOREA_BE → Settings → Actions → Runners → **New self-hosted runner** → Linux x64.
화면의 명령을 서버에서 그대로 실행하되 `./config.sh`에 라벨을 붙입니다.

```bash
./config.sh --url https://github.com/Hyun731/PTKOREA_BE --token <화면의 토큰> --labels madp --unattended
sudo ./svc.sh install ubuntu && sudo ./svc.sh start     # 재부팅 후에도 자동 실행
```

PTKOREA_BE → Settings → Environments 에 `production`을 만들어 두면 배포 이력이 남습니다(보호 규칙은 선택).

## 4. 첫 배포

main에 push하거나 Actions → deploy → **Run workflow**. 끝나면 서버에서:

```bash
curl -s localhost:8000/healthz
docker compose -f /opt/ptk/docker-compose.yml ps
```

## 5. 기존 데이터 옮기기 (한 번)

로컬 Docker 백엔드의 SQLite와 파일을 서버로 옮깁니다. 첫 배포가 끝나 서버 DB가 최신 스키마인 상태에서 합니다.

```bash
# (로컬) 파일 묶기: DB는 도구가 따로 옮김, 큰 백업/로그는 제외
cd backend
tar czf /tmp/ptk-var.tgz --exclude='var/backups' --exclude='*.log' --exclude='var/dev.db*' var/storage var/output
# 서버로 전송 (tsh 또는 scp 등), 서버에서 볼륨에 풀기
docker run --rm -v ptk_appdata:/app/var -v /tmp:/in alpine sh -c 'cd /app && tar xzf /in/ptk-var.tgz'
```

DB 행 복사는 서버의 Postgres가 밖에 열려 있지 않으니 서버 안에서 이미지로 실행합니다.

```bash
# (서버) dev.db를 /tmp에 올린 뒤
source <(grep ^POSTGRES_PASSWORD /opt/ptk/.env)
docker run --rm --network ptk_default -v /tmp/dev.db:/src/dev.db:ro \
  -e PTK_SKIP_DOTENV=1 "$(cat /opt/ptk/current_image)" \
  python -m tools.sqlite_to_postgres /src/dev.db "postgresql+psycopg://ptk:${POSTGRES_PASSWORD}@db:5432/ptk"
```

## 6. 마무리

- Vercel `API_ORIGIN`을 새 주소로 바꾸고 재배포(ngrok 도메인을 그대로 옮겼다면 바꿀 필요 없음).
- Render 서비스·Postgres(2026-11-28 만료)는 확인 후 정리.

## 운영

| 할 일 | 명령 (서버, `/opt/ptk`) |
|---|---|
| 로그 | `docker compose logs -f api` |
| 특정 버전으로 되돌리기 | Actions에서 그 커밋으로 Re-run, 또는 `~/actions-runner/_work/.../deploy/deploy.sh ghcr.io/hyun731/ptkorea-be:<sha>` |
| DB 백업 | `docker compose exec -T db pg_dump -U ptk ptk \| gzip > backup-$(date +%F).sql.gz` |

자동 롤백은 이미지만 되돌립니다. 마이그레이션은 되돌리지 않으므로, 칸을 지우거나 이름을 바꾸는 마이그레이션은 새 코드와 옛 코드가 둘 다 동작하게 나눠서 넣어 주세요.
