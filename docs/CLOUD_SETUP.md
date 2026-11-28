# Hướng dẫn set up môi trường Cloud

waterpeach có 2 môi trường, chọn bằng biến `APP_ENV`:

| | `local` | `cloud` |
|---|---|---|
| Database | Postgres 16 trong docker compose | Supabase PostgreSQL |
| Redis | Container `redis` | Upstash Redis (`rediss://`) hoặc tắt (`REDIS_URL=` rỗng) |
| API | `docker compose` hoặc `uv run uvicorn` | Google Cloud Run |
| Web | `docker compose` hoặc `pnpm dev` | Vercel |
| File biến môi trường | `.env` tạo từ `.env.example` (có trong repo) | `.env.cloud` tạo theo hướng dẫn này, **không commit** |

Khi `APP_ENV=cloud`, API **từ chối khởi động** nếu cấu hình còn giá trị local:
`B2B_API_KEY` rỗng hoặc bằng `wp_dev_b2b_api_key`, `DATABASE_URL` trỏ về `localhost`/`postgres`,
`DEBUG=true`, hoặc `CORS_ORIGINS` chứa `localhost`.

> `.env.cloud` đã nằm trong `.gitignore`. Không commit file này, không dán secret vào issue, PR hay slide.
> File zip nộp bài chỉ kèm `.env.example`.

---

## 1. Tạo file `.env.cloud` (chỉ trên máy bạn)

Tạo 2 file sau, điền giá trị thật ở các bước 2–4:

**`waterpeach-api/.env.cloud`**

```dotenv
APP_NAME=waterpeach-api
APP_ENV=cloud
DEBUG=false

SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_ANON_KEY=<supabase-anon-key>
SUPABASE_SERVICE_ROLE_KEY=<supabase-service-role-key>

# Runtime: Transaction pooler (cổng 6543)
DATABASE_URL=postgresql+asyncpg://postgres.<project-ref>:<db-password>@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres
# Alembic: Session pooler hoặc Direct connection (cổng 5432)
DIRECT_URL=postgresql+asyncpg://postgres.<project-ref>:<db-password>@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres

# Upstash Redis, hoặc để trống để tắt Redis
REDIS_URL=

GEMINI_API_KEY=<google-gemini-api-key>
GEMINI_MODEL=gemini-4-hydrogen

# openssl rand -hex 32
B2B_API_KEY=<strong-random-key>

CORS_ORIGINS=["https://<your-app>.vercel.app"]
```

**`waterpeach-web/.env.cloud`** (bản ghi để khai báo trên Vercel)

```dotenv
NEXT_PUBLIC_API_URL=https://<waterpeach-api-xxxx>.a.run.app
NEXT_PUBLIC_WS_URL=wss://<waterpeach-api-xxxx>.a.run.app
NEXT_PUBLIC_SUPABASE_URL=https://<project-ref>.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<supabase-anon-key>
```

Kiểm tra file đúng định dạng và không bị Git theo dõi:

```bash
git check-ignore waterpeach-api/.env.cloud waterpeach-web/.env.cloud   # phải in ra cả 2 đường dẫn
cd waterpeach-api
ENV_FILE=.env.cloud uv run python -c "from app.core.config import get_settings as g; s=g(); print(s.APP_ENV, s.uses_transaction_pooler)"
# Kết quả mong đợi: cloud True
```

## 2. Supabase (Database)

1. Tạo project tại <https://supabase.com/dashboard>, region **Southeast Asia (Singapore)** để gần Cloud Run `asia-southeast1`.
2. **Project Settings → API**: lấy `Project URL` → `SUPABASE_URL`, `anon` key → `SUPABASE_ANON_KEY`,
   `service_role` key → `SUPABASE_SERVICE_ROLE_KEY` (chỉ dùng ở API, không bao giờ đưa vào web).
3. **Connect → Connection string**:
   - **Transaction pooler** (cổng `6543`) → `DATABASE_URL`. API tự tắt prepared statement cache và dùng `NullPool` khi thấy cổng 6543.
   - **Session pooler** (cổng `5432`) → `DIRECT_URL` cho Alembic. Dùng "Direct connection" nếu mạng của bạn có IPv6.
   - Đổi tiền tố `postgresql://` thành `postgresql+asyncpg://`.

## 3. Redis (tùy chọn)

- Dùng Redis: tạo database tại <https://console.upstash.com>, region `ap-southeast-1`, copy URL dạng `rediss://default:<password>@<host>:6379` → `REDIS_URL`.
- Không dùng Redis: để `REDIS_URL=` rỗng. `/health/ready` sẽ báo `"redis": "skipped"`.

## 4. Gemini và B2B key

- `GEMINI_API_KEY`: tạo tại <https://aistudio.google.com/apikey>. Thiếu key thì AI chạy fallback heuristic (`used_fallback = true`).
- `B2B_API_KEY`: sinh bằng `openssl rand -hex 32`; đối tác B2B gửi qua header `X-API-Key`.

## 5. Deploy API lên Google Cloud Run

Yêu cầu: đã cài [gcloud CLI](https://cloud.google.com/sdk/docs/install) và có project GCP đã bật billing.

```bash
gcloud auth login
gcloud config set project <gcp-project-id>
gcloud config set run/region asia-southeast1
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com
```

### 5.1. Đưa secret lên Secret Manager

Chạy từ thư mục `waterpeach-api`, đọc giá trị trong `.env.cloud` (không in ra màn hình):

```bash
for name in DATABASE_URL DIRECT_URL SUPABASE_SERVICE_ROLE_KEY GEMINI_API_KEY B2B_API_KEY REDIS_URL; do
  value="$(grep -E "^${name}=" .env.cloud | cut -d= -f2-)"
  secret="wp-$(echo "$name" | tr 'A-Z_' 'a-z-')"
  gcloud secrets describe "$secret" >/dev/null 2>&1 || gcloud secrets create "$secret" --replication-policy=automatic
  printf '%s' "$value" | gcloud secrets versions add "$secret" --data-file=-
done
```

> Nếu không dùng Redis thì bỏ `REDIS_URL` khỏi vòng lặp và khỏi `--set-secrets` bên dưới
> (Secret Manager không nhận giá trị rỗng).

Cấp quyền đọc secret cho service account chạy Cloud Run (mặc định là Compute Engine default SA):

```bash
PROJECT_NUMBER="$(gcloud projects describe "$(gcloud config get-value project)" --format='value(projectNumber)')"
gcloud projects add-iam-policy-binding "$(gcloud config get-value project)" \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

### 5.2. Deploy

Chạy từ thư mục gốc repo. `^@^` đổi ký tự phân cách sang `@` để `CORS_ORIGINS` (JSON có dấu phẩy) không bị cắt.
Lần đầu chưa có domain Vercel thì đặt tạm `CORS_ORIGINS=["https://placeholder.vercel.app"]`, cập nhật ở bước 7.

```bash
gcloud run deploy waterpeach-api \
  --source waterpeach-api \
  --allow-unauthenticated \
  --min-instances 1 \
  --max-instances 1 \
  --timeout 3600 \
  --set-env-vars '^@^APP_ENV=cloud@DEBUG=false@GEMINI_MODEL=gemini-4-hydrogen@SUPABASE_URL=https://<project-ref>.supabase.co@CORS_ORIGINS=["https://<your-app>.vercel.app"]' \
  --set-secrets 'DATABASE_URL=wp-database-url:latest,DIRECT_URL=wp-direct-url:latest,SUPABASE_SERVICE_ROLE_KEY=wp-supabase-service-role-key:latest,GEMINI_API_KEY=wp-gemini-api-key:latest,B2B_API_KEY=wp-b2b-api-key:latest,REDIS_URL=wp-redis-url:latest'
```

- `--min-instances 1`: tránh cold start khi giám khảo mở demo.
- `--max-instances 1`: sự kiện realtime (WebSocket/SSE) chỉ phát trong một tiến trình; nhiều instance thì màn hình này có thể không thấy sự kiện của màn hình kia.
- `--timeout 3600`: giữ kết nối WebSocket `/api/v1/ws/events` lâu nhất có thể.
- Container đọc biến `PORT` do Cloud Run cấp (Dockerfile mặc định 8000 khi chạy local).
- Mỗi lần khởi động, container chạy `alembic upgrade head` qua `DIRECT_URL` rồi nạp dữ liệu demo nếu DB còn trống
  (Bác Minh, Anh Nam, Chị Linh). Muốn tắt bước này: thêm `RUN_MIGRATIONS_ON_START=false` vào `--set-env-vars`
  và chạy migration thủ công theo bước 9.

Lấy URL dịch vụ:

```bash
gcloud run services describe waterpeach-api --format='value(status.url)'
```

## 6. Deploy Web lên Vercel

1. Vào <https://vercel.com/new>, import repo GitHub, **Root Directory** = `waterpeach-web` (Framework: Next.js, Vercel tự nhận pnpm).
2. **Settings → Environment Variables** (môi trường Production): khai báo 4 biến trong `waterpeach-web/.env.cloud`,
   với `NEXT_PUBLIC_API_URL` là URL Cloud Run ở bước 5 và `NEXT_PUBLIC_WS_URL` cùng host nhưng scheme `wss://`.
3. Deploy. Vì `NEXT_PUBLIC_*` được nhúng lúc build, **mỗi lần đổi biến phải Redeploy**.

Hoặc dùng CLI:

```bash
cd waterpeach-web
pnpm dlx vercel link
pnpm dlx vercel env add NEXT_PUBLIC_API_URL production   # lặp lại cho 4 biến
pnpm dlx vercel --prod
```

## 7. Nối Web và API (CORS)

Sau khi có domain Vercel, cập nhật CORS cho API:

```bash
gcloud run services update waterpeach-api \
  --update-env-vars '^@^CORS_ORIGINS=["https://<your-app>.vercel.app"]'
```

Có thêm domain preview thì liệt kê đủ trong mảng JSON, ví dụ `["https://a.vercel.app","https://b.vercel.app"]`.

## 8. Kiểm tra sau deploy

```bash
API=https://<waterpeach-api-xxxx>.a.run.app
curl -s "$API/health"          # {"status":"ok","service":"waterpeach-api"}
curl -s "$API/health/ready"    # {"status":"ok","env":"cloud","checks":{"database":"ok","redis":"ok|skipped"}}
```

- `/health/ready` trả `503` + `"database": "fail"`: kiểm tra `DATABASE_URL` (cổng 6543, tiền tố `postgresql+asyncpg://`, mật khẩu đã URL-encode).
- Revision không lên, log có `Invalid cloud configuration: ...`: sửa đúng biến được nêu trong thông báo
  (`gcloud run services logs read waterpeach-api --limit 50`).
- Web gọi API bị chặn CORS: domain Vercel chưa có trong `CORS_ORIGINS` (bước 7).

## 9. Chạy lệnh local với cấu hình cloud

Dùng khi cần chạy migration/seed lên Supabase từ máy mình:

```bash
cd waterpeach-api
ENV_FILE=.env.cloud uv run alembic upgrade head      # tạo/cập nhật bảng trên Supabase
ENV_FILE=.env.cloud uv run python -m app.seed         # nạp dữ liệu demo nếu DB trống
ENV_FILE=.env.cloud uv run python -m app.seed --reset # xóa và nạp lại dữ liệu demo
```

Trong lúc demo có thể reset dữ liệu bằng `POST /api/v1/demo/reset`.

Biến môi trường thật luôn được ưu tiên hơn giá trị trong file.

## 10. Đóng băng sau hạn nộp

Thể lệ cấm cập nhật sản phẩm đang chạy sau 03/12: không deploy revision mới lên Cloud Run và Vercel đến hết 11/12.
Giữ `--min-instances 1` để demo luôn sẵn sàng.
