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
- **`PsychologicalTactic`**: `"URGENCY"` | `"AUTHORITY"` | `"FEAR"` | `"GREED"`
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
Kiểm tra tình trạng server, Supabase DB và Redis.
- **Response `200 OK`:**
```json
{
  "status": "ok",
  "service": "waterpeach-api"
}
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
  "timestamp": "2026-11-25T14:30:00+07:00"
}
```
- **Response `200 OK`:**
```json
{
  "tx_id": "tx_9f8a7b6c",
  "status": "cooling_off",
  "cooling_off_seconds": 900,
  "blacklist_hit": false,
  "ai_analysis": {
    "risk_score": 94,
    "risk_level": "CRITICAL",
    "scam_category": "POLICE_IMPERSONATION",
    "reasoning_for_victim": "Giao dịch này có nội dung giống kịch bản mạo danh cơ quan chức năng yêu cầu chuyển tiền xác minh. Hệ thống đã tạm giữ 15 phút để người thân kiểm tra giúp bác.",
    "reasoning_for_guardian": "Phát hiện nội dung chuyển khoản chứa dấu hiệu giả danh cơ quan công an yêu cầu nộp tiền xác minh, vượt ngưỡng giao dịch 5.000.000đ."
  },
  "guardian_notified": true
}
```

---

## 4. Phân hệ 1: Embedded Banking UI (Mobile Banking & Trusted Circle)

### `GET /api/v1/users/{user_id}/profile`
Lấy hồ sơ tài khoản Mobile Banking của Thành viên được bảo vệ (Bác Minh) để hiển thị màn hình Home: số dư ví thật (`balance`), số tài khoản, cấu hình ngưỡng bảo vệ và lịch sử giao dịch gần đây.
- **Ràng buộc Privacy-First:** Endpoint này chỉ phục vụ màn hình Mobile Banking của chính chủ tài khoản (`victim`), tuyệt đối không dùng cho vai trò `guardian`.
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
  "created_at": "2026-11-25T14:30:00+07:00"
}
```

### `GET /api/v1/family/trusted-circle?victim_id={victim_id}`
Lấy danh sách thành viên trong Vòng tròn tin cậy (nhóm gia đình) và cấu hình ngưỡng bảo vệ (Privacy-First).

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
- **Response `201 Created`:** Trả về đối tượng `FamilyLink` vừa tạo (`link_id`, `guardian_id`, `guardian_name`, `relationship`, `privacy_mode: "alert_only"`, `status: "active"`).

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
      "victim_name": "Bác Minh",
      "relationship": "Bố",
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
- **`hold_verify` (Nút Vàng):** Gia hạn `cooling_off_expires_at` thêm 30 phút và trả về danh sách câu hỏi gợi ý xác minh nhẹ nhàng.
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

### `GET /api/v1/family/safety-feed?family_member_id={user_id}`
Lấy Bảng tin An toàn Gia đình gồm các báo cáo lừa đảo đã được chia sẻ cho cả nhà.

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
  "shared_to_family": true,
  "created_at": "2026-11-25T14:35:00+07:00"
}
```

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
      "victim_age_group": "60+",
      "amount": 25000000,
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
    "cross_family_alert": true
  },
  "deescalation_copilot": {
    "victim_psychological_state": "Lo âu, bị cô lập bởi kịch bản đe dọa pháp lý",
    "call_script": "Chào bác Minh, cháu là Linh từ bộ phận Bảo vệ Khách hàng. Giao dịch 25 triệu đồng của bác đang được hệ thống và anh Nam tạm giữ để bảo vệ tài sản...",
    "guidance_sms": "Cảnh báo: Công an/Tòa án KHÔNG bao giờ yêu cầu chuyển tiền qua tài khoản cá nhân để xác minh hồ sơ."
  }
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
- **Response `200 OK`:** Trả về trạng thái cập nhật của giao dịch, bản ghi blacklist mới tạo (nếu có) và payload `incident_report` JSON chuẩn hóa.

### `GET /api/v1/ops/blacklist` & `POST /api/v1/ops/blacklist`
Tra cứu và bổ sung thủ công thực thể vào Threat Blacklist (`bank_account`, `phone`, `url`).

---

## 8. AI Engine Direct Endpoints (Debugging & SDK Testing)

3 endpoint ánh xạ trực tiếp tới 3 động cơ AI cốt lõi trong Proposal:
- `POST /api/v1/ai/analyze-tx` — Chấm điểm rủi ro ngữ cảnh cho payload giao dịch JSON.
- `POST /api/v1/ai/analyze-scam` — Phân tích đa phương thức ảnh/text/audio.
- `POST /api/v1/ai/ops-copilot` — Sinh Case Brief & Call Script hạ nhiệt từ ngữ cảnh hồ sơ.

---

## 9. Zero-Friction Demo & Realtime Event Contract

### 9.1. Demo Endpoints
- `POST /api/v1/demo/scenario/{scenario_id}` (`1`, `2`, hoặc `3`): Kích hoạt nhanh 1 trong 3 kịch bản mẫu từ Proposal.
- `POST /api/v1/demo/reset`: Khôi phục dữ liệu sạch về trạng thái demo ban đầu (xóa giao dịch phát sinh, nạp lại seed users: Bác Minh, Anh Nam, Chị Linh).

### 9.2. Realtime Event Payload (`ws://localhost:8000/api/v1/ws/events`)
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
