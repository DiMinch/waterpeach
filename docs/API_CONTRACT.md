# API Contract — `waterpeach` (v1)

Tài liệu đặc tả giao thức giao tiếp giữa **Frontend (`waterpeach-web`)**, **Core Banking Partners (B2B SDK/API)** và **Unified Backend & AI Server (`waterpeach-api`)**.

- **Base URL (Local):** `http://localhost:8000`
- **API Prefix:** `/api/v1`
- **Swagger / OpenAPI UI:** `http://localhost:8000/docs`
- **Realtime Transport:** WebSocket (`ws://localhost:8000/api/v1/ws/events`) hoặc SSE (`GET /api/v1/events/stream`) + Supabase Realtime.

---

## 1. Quy ước Chung & Enums

### 1.1. Headers
- `Content-Type: application/json` (trừ endpoint upload ảnh sử dụng `multipart/form-data`)
- `X-API-Key: <B2B_API_KEY>` (bắt buộc cho nhóm endpoint B2B Partner `/api/v1/risk/*`)

### 1.2. Chuẩn Trạng thái & Enum
- **`UserRole`**: `"victim"` | `"guardian"` | `"fraud_ops"`
- **`RiskLevel`**: `"LOW"` | `"MEDIUM"` | `"HIGH"` | `"CRITICAL"`
- **`TransactionStatus`**: `"completed"` | `"cooling_off"` | `"blocked"` | `"released"`
- **`GuardianDecision`**: `"pending"` | `"flag_scam"` | `"approve_safe"` | `"hold_verify"`
- **`OpsDecision`**: `"pending"` | `"confirmed_fraud"` | `"false_positive"`
- **`PsychologicalTactic`**: `"AUTHORITY"` | `"URGENCY"` | `"FEAR"` | `"GREED"` | `"RECIPROCITY_COMMITMENT"`
- **`VictimAgeGroup`**: `"under_18"` | `"18_25_student"` | `"26_55_adult"` | `"55_plus_senior"`
- **`GuardianRelationship`**: `"parent_of_victim"` | `"child_of_victim"` | `"spouse"` | `"other"`
- **`RecipientEntityType`**: `"INDIVIDUAL"` | `"MERCHANT_HKD"` | `"CORPORATION"` | `"UNKNOWN"`
- **`EntityType`**: `"bank_account"` | `"phone"` | `"url"`

### 1.3. Chuẩn Lỗi HTTP
```json
{
  "detail": "Transaction not found",
  "error_code": "TX_NOT_FOUND"
}
```

---

## 2. Health & System

### `GET /health`
Liveness: server đang chạy (không kiểm tra DB/Redis).
- **Response `200 OK`:**
```json
{
  "status": "ok",
  "service": "waterpeach-api"
}
```

### `GET /health/ready`
Readiness: kiểm tra Database và Redis (Redis `skipped` khi `REDIS_URL` rỗng). Trả `503` + `"status": "degraded"` nếu có thành phần lỗi.
```json
{ "status": "ok", "env": "local", "checks": { "database": "ok", "redis": "ok" } }
```

---

## 3. B2B Partner Risk API (Core Banking Integration)

### `POST /api/v1/risk/evaluate`
Endpoint chuẩn B2B cho phép Core Banking / Ví điện tử gửi payload giao dịch để chấm điểm rủi ro ngữ cảnh trước khi giải ngân.
- **Headers:** `X-API-Key: <B2B_API_KEY>`
- **Request Body:**
```json
{
  "partner_tx_ref": "MOMO-20261125-001",
  "sender_id": "usr_minh_01",
  "recipient_name": "NGUYEN VAN A",
  "recipient_account": "190388889999",
  "recipient_bank": "Techcombank",
  "amount": 25000000,
  "transfer_note": "Nop tien tam giu xac minh ho so",
  "device_id": "dev_iphone_minh",
  "timestamp": "2026-11-25T14:30:00+07:00",
  "in_active_call": false,
  "is_copy_pasted_account": false
}
```
*(`in_active_call`, `is_copy_pasted_account`: telemetry tùy chọn, mặc định `false`. `sender_id` phải là tài khoản `victim` đã có trong hệ thống.)*
- **Response `200 OK`:**
```json
{
  "tx_id": "tx_9f8a7b6c",
  "partner_tx_ref": "MOMO-20261125-001",
  "status": "cooling_off",
  "cooling_off_seconds": 900,
  "blacklist_hit": false,
  "ai_analysis": {
    "risk_score": 94,
    "risk_level": "CRITICAL",
    "scam_category": "POLICE_IMPERSONATION",
    "reasoning_for_victim": "Giao dịch này có nội dung giống kịch bản mạo danh cơ quan chức năng yêu cầu chuyển tiền xác minh. Hệ thống đã tạm giữ 15 phút để người thân kiểm tra giúp bác.",
    "reasoning_for_guardian": "Phát hiện nội dung chuyển khoản chứa dấu hiệu giả danh cơ quan công an yêu cầu nộp tiền xác minh, vượt ngưỡng giao dịch 5.000.000đ.",
    "detected_signals": ["FIRST_TIME_PAYEE", "ENTITY_CONTEXT_MISMATCH"],
    "used_fallback": false
  },
  "guardian_notified": true
}
```
- **Lỗi:** `401` thiếu/sai `X-API-Key`; `400 INSUFFICIENT_BALANCE`; `403 ROLE_NOT_ALLOWED`; `404 USER_NOT_FOUND`.

---

## 4. Phân hệ 1: Embedded Banking UI (Mobile Banking & Trusted Circle)

### `GET /api/v1/users/{user_id}/profile`
Lấy hồ sơ tài khoản Mobile Banking của Thành viên được bảo vệ (Bác Minh) để hiển thị màn hình Home: số dư ví thật (`balance`), số tài khoản, cấu hình ngưỡng bảo vệ và lịch sử giao dịch gần đây.
- **Ràng buộc Privacy-First:** Endpoint này chỉ phục vụ màn hình Mobile Banking của chính chủ tài khoản (`victim`), tuyệt đối không dùng cho vai trò `guardian` (user khác `victim` → `403 PROFILE_VICTIM_ONLY`).
- **Response `200 OK`:**
```json
{
  "user_id": "usr_minh_01",
  "name": "Bác Minh",
  "role": "victim",
  "phone": "0901234567",
  "account_number": "1012345678",
  "bank_name": "MoMo / Vietcombank",
  "balance": 85000000,
  "protection_threshold": 5000000,
  "sensitive_hours_enabled": true,
  "recent_transactions": [
    {
      "tx_id": "tx_seed_01",
      "recipient_name": "Siêu thị Co.opmart",
      "amount": 450000,
      "status": "completed",
      "created_at": "2026-11-24T09:15:00+07:00"
    }
  ]
}
```

### `GET /api/v1/transactions/lookup-account?bank={bank}&account={account}&sender_id={sender_id}`
Tra cứu tên chủ tài khoản nhận theo thời gian thực khi người dùng nhập STK trên màn hình chuyển tiền Mobile Banking, đồng thời kiểm tra xem người nhận là người quen, người lạ mới, hay đã nằm trong `threat_blacklist`.
- **Response `200 OK`:**
```json
{
  "account_number": "190388889999",
  "bank_name": "Techcombank",
  "account_holder_name": "NGUYEN VAN A",
  "is_familiar_recipient": false,
  "blacklist_status": "none",
  "warning_banner": null
}
```
*(Nếu `blacklist_status` là `"suspected"` hoặc `"confirmed_blacklisted"`, trả về `warning_banner` để hiển thị cảnh báo ngay trên form chuyển tiền.)*

### `POST /api/v1/transactions/transfer`
Khởi tạo giao dịch chuyển tiền từ giao diện Embedded Banking UI (Bác Minh). Gọi qua cùng lõi Risk Engine + Social Circuit Breaker, trừ/tạm giữ số dư thật trên tài khoản `balance`.
- **Request Body:** Tương tự `POST /api/v1/risk/evaluate` (không bắt buộc `X-API-Key` cho demo web client).
- **Response `201 Created`:** Trả về object `TransactionDetail` kèm `cooling_off_expires_at` (ISO-8601) nếu bị tạm giữ.
- **Máy trạng thái & số dư:** `completed` trừ tiền ngay; `cooling_off` tạm giữ (trừ khỏi `balance`); `blocked` hoàn lại phần tạm giữ; `released` giải ngân phần tạm giữ. Tài khoản nhận đã `confirmed_blacklisted` → `blocked` ngay, không trừ tiền.
- **Hết giờ cooling-off mà chưa ai quyết định:** giao dịch vẫn ở `cooling_off` (tiền vẫn tạm giữ) cho tới khi người giám hộ hoặc Fraud Ops xử lý.
- **Lỗi:** `400 INSUFFICIENT_BALANCE`, `403 ROLE_NOT_ALLOWED`, `404 USER_NOT_FOUND`.

### `GET /api/v1/transactions/{tx_id}`
Lấy trạng thái mới nhất của giao dịch (bao gồm đếm ngược cooling-off, phản hồi của người giám hộ và Fraud Ops).
- **Response `200 OK`:**
```json
{
  "tx_id": "tx_9f8a7b6c",
  "sender_id": "usr_minh_01",
  "sender_name": "Bác Minh",
  "recipient_name": "NGUYEN VAN A",
  "recipient_account": "190388889999",
  "recipient_bank": "Techcombank",
  "amount": 25000000,
  "transfer_note": "Nop tien tam giu xac minh ho so",
  "status": "cooling_off",
  "cooling_off_expires_at": "2026-11-25T14:45:00+07:00",
  "ai_risk_score": 94,
  "ai_analysis": {
    "risk_level": "CRITICAL",
    "scam_category": "POLICE_IMPERSONATION",
    "reasoning_for_victim": "...",
    "reasoning_for_guardian": "..."
  },
  "guardian_decision": "pending",
  "ops_decision": "pending",
  "blacklist_hit": false,
  "guardian_notified": false,
  "created_at": "2026-11-25T14:30:00+07:00"
}
```
*(`ai_analysis` còn có `risk_score`, `detected_signals`, `used_fallback`. `guardian_notified` chỉ có giá trị đúng trong response tạo giao dịch.)*

### `GET /api/v1/family/trusted-circle?victim_id={victim_id}`
Lấy danh sách thành viên trong Vòng tròn tin cậy (nhóm gia đình) và cấu hình ngưỡng bảo vệ (Privacy-First).
- **Response `200 OK`:** `{ "victim_id", "victim_name", "members": FamilyLink[], "settings": { "protection_threshold", "sensitive_hours_enabled", "auto_trigger_high_risk" }, "privacy_commitment" }`.

### `POST /api/v1/family/members`
Tạo / mời thêm thành viên giám hộ vào Nhóm Gia đình (Trusted Circle) của người được bảo vệ.
- **Request Body:**
```json
{
  "victim_id": "usr_minh_01",
  "guardian_name": "Chị Lan",
  "guardian_phone": "0912345678",
  "relationship": "Con gái"
}
```
- **Response `201 Created`:** Trả về đối tượng `FamilyLink` vừa tạo (`link_id`, `guardian_id`, `guardian_name`, `guardian_phone`, `relationship`, `privacy_mode: "alert_only"`, `status: "active"`).
- SĐT chưa có tài khoản sẽ được tạo user vai trò `guardian`. `relationship` là quan hệ của người giám hộ với người được bảo vệ (VD "Con gái"); hệ thống suy ra `GuardianRelationship` để AI chọn giọng văn.
- **Lỗi:** `409 MEMBER_EXISTS`, `409 PHONE_IN_USE`, `403 ROLE_NOT_ALLOWED`, `404 LINK_NOT_FOUND` (khi xóa).

### `DELETE /api/v1/family/members/{link_id}`
Gỡ bỏ một thành viên giám hộ khỏi Nhóm Gia đình (`Trusted Circle`).
- **Response `200 OK`:**
```json
{
  "deleted": true,
  "link_id": "lnk_02"
}
```

### `PUT /api/v1/family/settings`
Cập nhật ngưỡng bảo vệ cho người được bảo vệ (`protection_threshold`, `sensitive_hours_enabled`, `auto_trigger_high_risk`).
- **Request Body:**
```json
{
  "victim_id": "usr_minh_01",
  "protection_threshold": 5000000,
  "sensitive_hours_enabled": true
}
```
- Các trường cấu hình đều tùy chọn (chỉ cập nhật trường được gửi). **Response `200 OK`:** `ProtectionSettings`.
- Khung giờ nhạy cảm: 22:00–06:00 giờ Việt Nam.

---

## 5. Phân hệ 2: Family Guardian Hub (Người giám hộ)

### `GET /api/v1/guardian/alerts?guardian_id={guardian_id}`
Lấy danh sách cảnh báo khẩn cấp dành cho Người giám hộ (Anh Nam).
- **Ràng buộc Privacy-First:** Response **KHÔNG** trả về số dư tài khoản (`balance`) hoặc các giao dịch `completed` thông thường.
- **Response `200 OK`:**
```json
{
  "alerts": [
    {
      "tx_id": "tx_9f8a7b6c",
      "victim_id": "usr_minh_01",
      "victim_name": "Bác Minh",
      "relationship": "Con trai",
      "recipient_name": "NGUYEN VAN A",
      "amount": 25000000,
      "recipient_account": "190388889999",
      "recipient_bank": "Techcombank",
      "is_new_recipient": true,
      "status": "cooling_off",
      "cooling_off_expires_at": "2026-11-25T14:45:00+07:00",
      "ai_risk_score": 94,
      "risk_level": "CRITICAL",
      "reasoning_for_guardian": "Phát hiện nội dung chuyển khoản chứa dấu hiệu giả danh cơ quan công an...",
      "guardian_decision": "pending",
      "created_at": "2026-11-25T14:30:00+07:00"
    }
  ]
}
```

### `POST /api/v1/guardian/transactions/{tx_id}/decision`
Người giám hộ thực hiện quyết định 1-chạm:
- **`flag_scam` (Nút Đỏ):** Chuyển giao dịch sang `blocked`, đẩy hồ sơ lên mức `CRITICAL` ở Fraud Ops Workspace, gửi thông điệp trấn an cho nạn nhân.
- **`approve_safe` (Nút Xanh):** Chuyển giao dịch sang `released`, tự động đóng cảnh báo giả (`false_positive`) phía Fraud Ops.
- **`hold_verify` (Nút Vàng):** Gia hạn `cooling_off_expires_at` thêm 30 phút và trả về danh sách câu hỏi gợi ý xác minh nhẹ nhàng. Giao dịch vẫn `cooling_off`, người giám hộ vẫn bấm Đỏ/Xanh được sau đó.
- Chỉ áp dụng cho giao dịch đang `cooling_off` của người trong Trusted Circle. **Lỗi:** `403 ROLE_NOT_ALLOWED`, `403 NOT_GUARDIAN_OF_SENDER`, `409 TX_NOT_PENDING`, `409 INVALID_DECISION`.
- **Request Body:**
```json
{
  "guardian_id": "usr_nam_02",
  "decision": "flag_scam",
  "note": "Bố đang bị gọi điện giả danh công an, chặn giúp tôi!"
}
```
- **Response `200 OK`:**
```json
{
  "tx_id": "tx_9f8a7b6c",
  "status": "blocked",
  "guardian_decision": "flag_scam",
  "ops_decision": "pending",
  "cooling_off_expires_at": "2026-11-25T14:45:00+07:00",
  "suggested_verification_questions": []
}
```

*(`relationship` trong cảnh báo là nhãn quan hệ lưu trên `FamilyLink`, tức quan hệ của người giám hộ với người được bảo vệ.)*

### `GET /api/v1/family/safety-feed?family_member_id={user_id}`
Lấy Bảng tin An toàn Gia đình gồm các báo cáo lừa đảo đã được chia sẻ cho cả nhà (cùng báo cáo riêng của chính người xem).
- **Response `200 OK`:** `{ "items": [{ "report_id", "submitted_by", "submitted_by_name", "verdict", "risk_score", "scam_category", "summary", "advice_for_family", "tactics_detected", "created_at" }] }`. Vai trò `fraud_ops` → `403`.

---

## 6. Multimodal Scam Check & Threat Intelligence

### `POST /api/v1/scam-check/analyze`
Phân tích ảnh chụp màn hình tin nhắn Zalo/SMS, công văn giả, hoặc đoạn text/audio cuộc gọi đáng ngờ bằng Gemini Multimodal.
- **Request (`multipart/form-data`):**
  - `submitted_by` (string, required)
  - `raw_text` (string, optional)
  - `file` (UploadFile image/audio, optional — phải có ít nhất `file` hoặc `raw_text`)
  - `share_to_family` (boolean, default `false`)
- **Response `200 OK`:**
```json
{
  "report_id": "rep_4421a",
  "verdict": "HIGH_RISK_SCAM",
  "risk_score": 91,
  "scam_category": "FAKE_SHIPPER_OR_TAX",
  "summary": "Tin nhắn giả mạo đơn vị vận chuyển/thuế yêu cầu truy cập đường link lạ và chuyển khoản phí xác thực.",
  "tactics_detected": [
    {
      "tactic": "URGENCY",
      "evidence": "Yêu cầu hoàn tất trong 2 giờ trước khi khóa mã vận đơn"
    },
    {
      "tactic": "AUTHORITY",
      "evidence": "Sử dụng con dấu/logo cắt ghép sai quy chuẩn"
    }
  ],
  "extracted_entities": {
    "bank_accounts": ["190388889999"],
    "phones": ["0987654321"],
    "urls": ["http://thue-xacminh-vn.xyz"]
  },
  "forensic_analysis": null,
  "advice_for_family": "Tuyệt đối không chuyển tiền hoặc bấm vào đường link trong tin nhắn này.",
  "blacklisted_entities_count": 3,
  "shared_to_family": true,
  "used_fallback": false,
  "created_at": "2026-11-25T14:35:00+07:00"
}
```
- Verdict khác `SAFE`: mọi thực thể trích xuất được đưa vào `threat_blacklist` ở trạng thái `suspected` (đã có thì tăng `report_count`). `share_to_family = true` phát sự kiện `FAMILY_SCAM_ALERT_SHARED`.
- **Lỗi:** `400 INVALID_SCAM_INPUT` (không có text lẫn file, file sai định dạng), `400 FILE_TOO_LARGE` (> 5 MB). Ảnh chưa được lưu lên storage nên chưa có `image_url`.

---

## 7. Phân hệ 3: Fintech Fraud Ops Future Workspace

### `GET /api/v1/ops/incidents`
Lấy Hàng đợi Ưu tiên Thông minh (AI-Triaged Incident Queue). Sắp xếp mặc định: case `flag_scam` lên đầu, tiếp theo theo `ai_risk_score` giảm dần; hỗ trợ lọc `?filter=all|active|auto_resolved`.
- **Response `200 OK`:**
```json
{
  "stats": {
    "critical_queue_count": 3,
    "auto_resolved_count": 12,
    "false_positive_reduction_pct": 75.0
  },
  "incidents": [
    {
      "tx_id": "tx_9f8a7b6c",
      "priority_badge": "CRITICAL_GUARDIAN_FLAGGED",
      "victim_name": "Bác Minh",
      "victim_age_group": "55_plus_senior",
      "amount": 25000000,
      "recipient_name": "NGUYEN VAN A",
      "recipient_account": "190388889999",
      "ai_risk_score": 94,
      "guardian_decision": "flag_scam",
      "ops_decision": "pending",
      "status": "blocked",
      "created_at": "2026-11-25T14:30:00+07:00"
    }
  ]
}
```

### `GET /api/v1/ops/incidents/{tx_id}/brief`
Lấy **AI Case Brief** tổng hợp + đối chiếu **Network Threat Intelligence** + **AI De-escalation Copilot** (Call Script cá nhân hóa).
- **Response `200 OK`:**
```json
{
  "tx_id": "tx_9f8a7b6c",
  "case_summary": "Khách hàng 65 tuổi thực hiện chuyển 25.000.000đ tới tài khoản lạ kèm nội dung 'Nop tien tam giu xac minh ho so'. Người giám hộ (con trai) đã bấm chặn khẩn cấp.",
  "recommended_action": "confirm_fraud_and_blacklist",
  "confidence_score": 0.96,
  "network_threat_intel": {
    "matched_reports_count": 2,
    "matched_entities": ["190388889999"],
    "cross_family_alert": true,
    "blacklist_status": "suspected"
  },
  "deescalation_copilot": {
    "victim_psychological_state": "Lo âu, bị cô lập bởi kịch bản đe dọa pháp lý",
    "call_script": "Chào bác Minh, cháu là Linh từ bộ phận Bảo vệ Khách hàng. Giao dịch 25 triệu đồng của bác đang được hệ thống và anh Nam tạm giữ để bảo vệ tài sản...",
    "guidance_sms": "Cảnh báo: Công an/Tòa án KHÔNG bao giờ yêu cầu chuyển tiền qua tài khoản cá nhân để xác minh hồ sơ.",
    "verification_questions": ["..."]
  },
  "priority_badge": "CRITICAL_GUARDIAN_FLAGGED",
  "used_fallback": false
}
```

### `POST /api/v1/ops/incidents/{tx_id}/action`
Thực hiện hành động 1-chạm (1-Click Containment Actions).
- **Request Body:**
```json
{
  "ops_id": "usr_linh_03",
  "action": "cancel_and_refund",
  "add_to_blacklist": true,
  "notes": "Xác nhận lừa đảo giả danh công an, hoàn tiền và khóa STK nhận."
}
```
*(Giá trị `action`: `"cancel_and_refund"` | `"blacklist_recipient"` | `"release_transaction"` | `"export_report"`)*
- **Response `200 OK`:** `{ "transaction": TransactionDetail, "blacklist_entry": BlacklistEntry | null, "incident_report": { "report_id", "generated_at", "ops_id", "ops_name", "action", "notes", "transaction", "network_threat_intel", "blacklist_entry" } }`.
- Hiệu lực: `cancel_and_refund` → `blocked` + hoàn tiền tạm giữ, `ops_decision = confirmed_fraud`; `blacklist_recipient` → như trên + STK nhận `confirmed_blacklisted`; `release_transaction` → `released`, `ops_decision = false_positive`; `export_report` không đổi trạng thái. `add_to_blacklist = true` đưa STK nhận vào blacklist với mọi hành động.
- **Lỗi:** `403 ROLE_NOT_ALLOWED` (không phải `fraud_ops`), `409 TX_NOT_AN_INCIDENT` (giao dịch `completed`), `409 TX_ALREADY_RESOLVED`.
- Hàng đợi: incident là mọi giao dịch khác `completed`; `active` = `cooling_off`/`blocked` và `ops_decision = pending`; `auto_resolved` = người giám hộ đã bấm `approve_safe`. `false_positive_reduction_pct` = tỉ lệ incident tự đóng nhờ người giám hộ.

### `GET /api/v1/ops/blacklist` & `POST /api/v1/ops/blacklist`
Tra cứu và bổ sung thủ công thực thể vào Threat Blacklist (`bank_account`, `phone`, `url`).
- **GET** query tùy chọn: `entity_type`, `status` (`suspected` | `confirmed_blacklisted`), `q` (tìm theo giá trị). Response `{ "entries": BlacklistEntry[] }`, `BlacklistEntry = { id, entity_type, entity_value, report_count, scam_pattern, status, created_at, updated_at }`.
- **POST** body `{ "entity_type", "entity_value", "scam_pattern"?, "status"? = "confirmed_blacklisted" }` → `201 BlacklistEntry`. Giá trị được chuẩn hóa (SĐT `+84` → `0`, STK chỉ giữ chữ số, URL chữ thường). Trạng thái chỉ tăng, không hạ.

---

## 8. AI Engine Direct Endpoints (Debugging & SDK Testing)

Chi tiết kiến trúc Ma trận Chấm điểm Đa chiều, thuật toán Giám định Ảnh (ELA) và cơ chế chống spam/tấn công xem tại **[docs/AI_ARCHITECTURE.md](AI_ARCHITECTURE.md)**. Các response dưới đây giữ nguyên định dạng thân thiện với người dùng cuối (không chứa `scientific_references`).

### `POST /api/v1/ai/analyze-tx`
Chấm điểm rủi ro ngữ cảnh đa chiều cho giao dịch (RFM/Structuring + Relationship Graph + Behavioral Telemetry + Semantic NLP + Entity/MST check).
- **Request Body:**
```json
{
  "amount": 25000000,
  "balance": 85000000,
  "recipient_name": "NGUYEN VAN A",
  "recipient_account": "190388889999",
  "recipient_bank": "Techcombank",
  "recipient_tax_code": null,
  "transfer_note": "Nop tien tam giu xac minh ho so",
  "persona_context": {
    "victim_age_group": "55_plus_senior",
    "guardian_relationship": "child_of_victim"
  },
  "relationship_context": {
    "prior_tx_count": 0,
    "protection_threshold": 5000000,
    "blacklist_hit": false
  },
  "velocity_context": {
    "tx_count_15m": 1,
    "cumulative_unfamiliar_amount_60m": 25000000,
    "seconds_since_last_tx": null,
    "is_sensitive_hours": false
  },
  "telemetry_context": {
    "in_active_call": true,
    "is_copy_pasted_account": true
  }
}
```
- **Response `200 OK`:**
```json
{
  "risk_score": 96,
  "risk_level": "CRITICAL",
  "recommended_status": "cooling_off",
  "cooling_off_seconds": 900,
  "scam_category": "POLICE_IMPERSONATION",
  "recipient_entity_type": "INDIVIDUAL",
  "merchant_verified": false,
  "detected_signals": [
    "FIRST_TIME_PAYEE",
    "ENTITY_CONTEXT_MISMATCH",
    "ACTIVE_CALL_COERCION_SIGNATURE",
    "THRESHOLD_EXCEEDED"
  ],
  "reasoning_for_victim": "Bác ơi, nội dung chuyển khoản này rất giống kịch bản giả danh cơ quan chức năng yêu cầu nộp tiền xác minh. Hệ thống tạm giữ 15 phút để người thân kiểm tra giúp bác nhé.",
  "reasoning_for_guardian": "Phát hiện chuyển 25.000.000đ tới tài khoản cá nhân mới trong lúc đang nghe điện thoại, nội dung có dấu hiệu giả danh công an tạm giữ hồ sơ.",
  "used_fallback": false
}
```

### `POST /api/v1/ai/analyze-scam`
Phân tích đa phương thức ảnh chụp màn hình tin nhắn Zalo/SMS, công văn giả hoặc đoạn text hội thoại (kết hợp Pixel-level ELA/EXIF Forensics + Gemini VLM + PhishVN URL Lexical Check + Regex IOC).
- Hỗ trợ JSON (`raw_text`, `image_base64`, `image_mime_type`) hoặc `multipart/form-data` (upload file tối đa `5 MB`, kiểm tra Magic Bytes).
- **Response `200 OK`:**
```json
{
  "verdict": "HIGH_RISK_SCAM",
  "risk_score": 92,
  "scam_category": "FAKE_AUTHORITY_DOCUMENT",
  "summary": "Công văn/tin nhắn có dấu hiệu giả mạo cơ quan chức năng nhằm đe dọa và yêu cầu chuyển tiền xác minh.",
  "forensic_analysis": {
    "software_signature": "Canva",
    "ela_anomaly_score": 78.4,
    "tampering_suspected": true,
    "forensic_note": "Phát hiện chữ ký phần mềm chỉnh sửa và bất thường mức nén điểm ảnh cục bộ tại vùng con dấu/số liệu."
  },
  "tactics_detected": [
    {
      "tactic": "AUTHORITY",
      "evidence": "Mạo danh cơ quan công an/thuế với văn phong đe dọa pháp lý"
    },
    {
      "tactic": "URGENCY",
      "evidence": "Yêu cầu chuyển tiền trong vòng 2 giờ"
    }
  ],
  "extracted_entities": {
    "bank_accounts": ["190388889999"],
    "phones": ["0987654321"],
    "urls": ["http://thue-xacminh-vn.xyz"]
  },
  "web_grounding_intel": {
    "searched": true,
    "summary": "Tên miền lạ không thuộc cổng thông tin chính thức của cơ quan nhà nước (.gov.vn).",
    "citations": []
  },
  "advice_for_family": "Tuyệt đối không chuyển tiền hoặc bấm vào đường link trong tin nhắn này."
}
```

### `POST /api/v1/ai/ops-copilot`
Sinh `case_summary`, mức độ ưu tiên (`priority_badge`), `call_script` hạ nhiệt tâm lý thích ứng theo `PersonaContext`, `guidance_sms` và 3 `verification_questions`.

### `POST /api/v1/ai/verify-entity`
Tra cứu pháp nhân & enrich ngữ cảnh bên ngoài cho `recipient_name`, `tax_code`, số điện thoại hoặc URL (kết hợp **VietQR Tax API `api.vietqr.io/v2/business/{taxCode}`** + **PhishVN URL Lexical Check** + **Google Search Grounding Agent**).
- **Request Body:**
```json
{
  "recipient_name": "CONG TY CO PHAN FPT",
  "tax_code": "0101248141",
  "url": null,
  "phone": null,
  "enable_web_search": true
}
```
- **Response `200 OK`:**
```json
{
  "recipient_entity_type": "CORPORATION",
  "tax_lookup": {
    "found": true,
    "tax_code": "0101248141",
    "legal_name": "CÔNG TY CỔ PHẦN FPT",
    "status": "NNT đang hoạt động",
    "address": "Số 10 phố Phạm Văn Bạch, Phường Cầu Giấy, TP Hà Nội"
  },
  "url_risk": null,
  "web_grounding_intel": {
    "searched": true,
    "summary": "Doanh nghiệp công nghệ niêm yết hợp pháp tại Việt Nam, không ghi nhận cảnh báo lừa đảo.",
    "citations": [
      {
        "title": "FPT Corporation",
        "url": "https://fpt.com"
      }
    ]
  }
}
```

---

## 9. Zero-Friction Demo & Realtime Event Contract

### 9.1. Demo Endpoints
- `POST /api/v1/demo/scenario/{scenario_id}` (`1`, `2`, hoặc `3`): Kích hoạt nhanh 1 trong 3 kịch bản mẫu từ Proposal.
- `POST /api/v1/demo/reset`: Khôi phục dữ liệu sạch về trạng thái demo ban đầu (xóa giao dịch phát sinh, nạp lại seed users: Bác Minh `usr_minh_01`, Anh Nam `usr_nam_02`, Chị Linh `usr_linh_03`). Response `{ "reset": true, "users": 3, "transactions": 3 }`.
- Response của `scenario`: `{ "scenario_id", "title", "next_step", "transaction": TransactionDetail | null, "scam_report": ScamCheckResponse | null }` (kịch bản 1, 2 trả `transaction`; kịch bản 3 trả `scam_report`).

### 9.2. Realtime Event Payload (`ws://localhost:8000/api/v1/ws/events`)
- Lọc theo vai trò: `?role=victim|guardian|fraud_ops` (bỏ trống = nhận tất cả). SSE dự phòng: `GET /api/v1/events/stream?role=...`, mỗi sự kiện gửi dạng `event: <EVENT>` + `data: <envelope JSON>`, keep-alive mỗi 15 giây.
- Payload giao dịch: `{ tx_id, status, risk_level, victim_id, amount, guardian_decision, ops_decision }` (+ `action` cho `OPS_CONTAINMENT_EXECUTED`). `FAMILY_SCAM_ALERT_SHARED`: `{ report_id, submitted_by, submitted_by_name, verdict, risk_score, summary }`. `DEMO_DATA_RESET`: `{ users, transactions }`.
- Sự kiện chỉ phát trong một tiến trình API: chạy 1 instance (Cloud Run `--max-instances 1`).

Mọi sự kiện real-time phát tới 3 phân hệ tuân theo cấu trúc envelope:
```json
{
  "event": "TX_COOLING_OFF_TRIGGERED",
  "timestamp": "2026-11-25T14:30:01+07:00",
  "target_roles": ["victim", "guardian", "fraud_ops"],
  "payload": {
    "tx_id": "tx_9f8a7b6c",
    "status": "cooling_off",
    "risk_level": "CRITICAL"
  }
}
```
Danh sách `event` chuẩn:
- `TX_COOLING_OFF_TRIGGERED`
- `GUARDIAN_DECISION_MADE`
- `OPS_INCIDENT_ESCALATED`
- `OPS_CONTAINMENT_EXECUTED`
- `FAMILY_SCAM_ALERT_SHARED`
- `DEMO_DATA_RESET`

---

## 10. Đặc tả UX: Mobile Banking Shell & Chế độ Xem Song Song (Split-View)

Để sản phẩm thể hiện đúng mô hình **Embedded SDK trong Ứng dụng Mobile Banking** thay vì một trang form demo đơn thuần:
- **Khung điện thoại Mobile-in-Web (`victim` & `guardian`):**
  - **Các luồng chạy thật 100% end-to-end (DB + AI + Realtime):** Màn hình Home hiển thị số dư thật (`balance`) & lịch sử giao dịch; luồng chuyển tiền + tra cứu STK người nhận (`lookup-account`) + Cầu dao xã hội (`cooling_off`); tạo/thêm/xóa thành viên nhóm gia đình (`Trusted Circle`) và cấu hình hạn mức; quét ảnh/tin nhắn lừa đảo đa phương thức (`scam-check`); xác nhận 1-chạm từ điện thoại người giám hộ.
  - **Các tiện ích ngân hàng phụ trợ (Visual Shell):** Nạp điện thoại, thanh toán hóa đơn, quét QR nhận tiền... hiển thị để hoàn thiện trải nghiệm Mobile Banking chân thực (khi nhấn hiện toast thông báo phạm vi demo).
- **Chế độ hiển thị (Role Switcher Bar):** Hỗ trợ chuyển đổi từng vai trò (*Bác Minh* / *Anh Nam* / *Chị Linh*) hoặc bật **Split-View (2 điện thoại cạnh nhau)** để quan sát giao dịch từ Bác Minh kích hoạt cảnh báo real-time trên máy Anh Nam ngay lập tức.
