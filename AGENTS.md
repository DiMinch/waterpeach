# AGENTS.md — Harness Engineering & Working Principles for `waterpeach`

Tài liệu này là **điểm chuẩn kỹ thuật (Engineering Harness)** dành cho cả thành viên phát triển và AI coding agents làm việc trên monorepo `waterpeach`. Mọi thay đổi mã nguồn phải tuân thủ các ranh giới kiến trúc, quy chuẩn Git và quy trình kiểm thử dưới đây.

---

## 1. Quy trình Làm việc & Chiến lược Git (Git & Branching Strategy)

### 1.1. Mô hình Branch (Feature Branch Workflow)
- **`main`**: Nhánh ổn định nhất, luôn trong trạng thái **deployable & demo-ready** (dùng để deploy Vercel/Cloud Run và chấm giải). **Tuyệt đối không push trực tiếp lên `main`** khi đang phát triển tính năng mới.
- **Tạo nhánh theo tính năng / phạm vi (`<type>/<scope>-<short-desc>`):**
  - `feat/fe-<name>`: Tính năng Frontend trên `waterpeach-web` (VD: `feat/fe-victim-transfer`, `feat/fe-guardian-hub`, `feat/fe-ops-workspace`).
  - `feat/be-<name>`: Tính năng Backend Core API/DB/Realtime trên `waterpeach-api` (VD: `feat/be-risk-evaluate`, `feat/be-supabase-models`).
  - `feat/ai-<name>`: Tính năng AI Engine trên `waterpeach-api` (VD: `feat/ai-contextual-risk`, `feat/ai-multimodal-scam`).
  - `fix/<scope>-<issue>`: Sửa lỗi (VD: `fix/api-ws-reconnect`, `fix/web-countdown-timer`).
  - `docs/<topic>` / `chore/<task>`: Cập nhật tài liệu, CI/CD, cấu hình Docker/Supabase.

### 1.2. Quy ước Commit (Conventional Commits)
Sử dụng định dạng `<type>(<scope>): <imperative summary>`:
- `feat(web): add role switcher bar and demo scenario buttons`
- `feat(api): implement B2B risk evaluate endpoint and cooling-off state`
- `feat(ai): add Gemini structured output schema for scam analyzer`
- `fix(api): handle Gemini API timeout with graceful rule fallback`
- `docs(contract): update incident brief response schema`

### 1.3. Quy tắc Atomic PR & Bảo mật
- Mỗi branch/PR chỉ giải quyết **1 vertical slice** rõ ràng (tránh trộn sửa UI hàng loạt với thay đổi DB migration không liên quan).
- **Tuyệt đối không commit** các tệp `.env`, `.env.local`, `SUPABASE_SERVICE_ROLE_KEY`, hoặc `GEMINI_API_KEY` thật. Chỉ cập nhật `.env.example` khi thêm biến môi trường mới.
- Khi thay đổi schema/endpoint API, **bắt buộc cập nhật đồng bộ 3 nơi trong cùng PR**:
  1. [docs/API_CONTRACT.md](docs/API_CONTRACT.md)
  2. `waterpeach-api/app/schemas/` (Pydantic v2 DTOs)
  3. `waterpeach-web/src/types/` (TypeScript interfaces)

---

## 2. Diễn giải Cấu trúc Thư mục & Ranh giới Kiến trúc (Separation of Concerns)

### 2.1. `waterpeach-api/` (Unified FastAPI Backend + AI Engine)
Áp dụng kiến trúc phân tầng nghiêm ngặt để đảm bảo tách biệt giữa HTTP Transport, Business Logic, AI Inference và Data Persistence:

```text
waterpeach-api/
├── alembic/                  # Quản lý database migrations tới Supabase (sử dụng DIRECT_URL port 5432)
├── app/
│   ├── main.py               # Khởi tạo FastAPI app, đăng ký middleware CORS, lifespan & mount routers
│   ├── core/                 # Settings (pydantic-settings đọc .env), xác thực B2B X-API-Key, logging, exceptions
│   ├── db/                   # Kết nối Supabase PostgreSQL (AsyncSession via asyncpg), Supabase client, Redis client
│   ├── models/               # SQLAlchemy 2.0 Async ORM models (users, family_links, transactions, scam_reports, threat_blacklist)
│   ├── schemas/              # Pydantic v2 Request/Response DTOs & Gemini Structured Output schemas (Single Source of Truth)
│   ├── api/v1/               # Tầng HTTP/WebSocket Router: CHỈ parse request, inject dependencies, trả response.
│   │                         # CẤM viết truy vấn SQL hoặc logic nghiệp vụ trực tiếp trong router.
│   ├── services/             # Tầng nghiệp vụ cốt lõi:
│   │                         # - Transaction State Machine (completed -> cooling_off -> blocked | released)
│   │                         # - Trusted Circle & Privacy-First filtering
│   │                         # - Redis Blacklist cache & Realtime Event publisher (WebSocket / Supabase Realtime)
│   └── ai/                   # 3 Động cơ AI (google-genai SDK + Structured Outputs):
│                             # - Contextual Transaction Risk Engine
│                             # - Multimodal Scam Analyzer
│                             # - Agentic Fraud Ops Copilot
│                             # Bắt buộc có timeout & graceful fallback để không làm nghẽn luồng chuyển tiền.
└── tests/                    # Unit tests & API integration tests (pytest + pytest-asyncio + httpx)
```

### 2.2. `waterpeach-web/` (Next.js App Router Frontend)
```text
waterpeach-web/
├── src/
│   ├── app/                  # Next.js App Router pages, layout gốc, providers
│   ├── components/
│   │   ├── victim/           # Phân hệ 1: Embedded Banking UI (Bác Minh - Transfer, Cooling-off, Scam Check)
│   │   ├── guardian/         # Phân hệ 2: Family Guardian Hub (Anh Nam - Alert Card, 1-Tap Actions, Safety Feed)
│   │   ├── fraud-ops/        # Phân hệ 3: Fintech Fraud Ops Workspace (Chị Linh - Queue, AI Brief, Copilot, Blacklist)
│   │   └── shared/           # Top Role Switcher Bar, One-Click Test Scenarios, Reset Demo Data, B2B SDK Playground
│   ├── lib/                  # Typed API client (fetch wrapper), WebSocket/SSE & Supabase Realtime hooks, formatters
│   └── types/                # TypeScript interfaces ánh xạ 1-1 với docs/API_CONTRACT.md
└── public/                   # Static assets (ảnh mẫu kịch bản lừa đảo, icons, avatar)
```

---

## 3. Quy chuẩn Coding (Coding Standards)

### 3.1. Python (`waterpeach-api`)
- **Type Hints bắt buộc:** Mọi function/method đều phải có đầy đủ type annotations (Python 3.12+) và return type.
- **Async First:** Sử dụng `async def` cho toàn bộ FastAPI routes, SQLAlchemy queries (`AsyncSession`), Redis commands và HTTP calls. Không dùng blocking I/O (như `time.sleep` hoặc `requests`) trong async event loop.
- **Pydantic v2:** Sử dụng `BaseModel` với `ConfigDict(from_attributes=True)` và `Field(..., description=...)` để vừa sinh OpenAPI/Swagger tự động, vừa làm `response_schema` cho Gemini Structured Outputs.
- **Graceful AI Fallback:** Mọi lời gọi `google-genai` phải đặt trong `asyncio.wait_for(..., timeout=...)` và có fallback an toàn (heuristic/rule-based) nếu API chậm hoặc lỗi mạng.
- **Privacy-First Enforcement:** API trả về cho vai trò `guardian` **tuyệt đối không** bao gồm trường số dư tài khoản (`balance`) hoặc lịch sử giao dịch bình thường (`completed` không cảnh báo).

### 3.2. TypeScript / Next.js (`waterpeach-web`)
- **Strict TypeScript:** Tuyệt đối không dùng `any`. Mọi payload API đều phải có interface trong `src/types/`.
- **UI/UX Consistency:**
  - Phân hệ **Bác Minh (Victim)**: chữ lớn rõ ràng, ngôn ngữ bình dân, tránh thuật ngữ kỹ thuật gây hoảng loạn.
  - Phân hệ **Anh Nam (Guardian)**: nhấn mạnh 3 nút hành động Đỏ / Xanh / Vàng trực quan và cam kết Privacy-First.
  - Phân hệ **Chị Linh (Fraud Ops)**: thiết kế mật độ thông tin chuyên nghiệp (Future Workspace), thao tác 1-chạm nhanh.
- **Client/Server Boundaries:** Đánh dấu `'use client'` rõ ràng cho các component dùng state, timer đếm ngược, WebSocket hoặc upload file.

---

## 4. Cổng Kiểm tra Trước khi Merge (Harness Verification Gate)

Mọi thay đổi trước khi merge vào `main` phải chạy qua bộ lệnh kiểm tra sau và **không có lỗi**:

```bash
# Backend & AI (waterpeach-api)
uv --directory waterpeach-api run ruff check .
uv --directory waterpeach-api run pytest --cov=app --cov-report=term-missing --cov-fail-under=80

# Frontend (waterpeach-web)
pnpm --dir waterpeach-web lint
pnpm --dir waterpeach-web build
```
