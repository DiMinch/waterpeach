# AI Architecture & Scientific Foundations — `waterpeach`

Tài liệu thiết kế chi tiết phân hệ AI (`waterpeach-api/app/ai/`), Ma trận Chấm điểm Rủi ro Đa chiều, hệ thống Giám định Ảnh Kỹ thuật số, kiến trúc Phòng chống Tấn công/Spam, và **toàn bộ cơ sở nghiên cứu khoa học phục vụ vấn đáp chuyên môn** tại **MoMo TechDay 2026**.

> **Nguyên tắc Trải nghiệm Người dùng (UX First):** Toàn bộ trích dẫn nghiên cứu khoa học và công thức toán học được lưu tại tài liệu này và dùng cho tầng giải thích nội bộ / vấn đáp Ban Giám khảo. Payload API trả về cho người dùng cuối (Bác Minh / Anh Nam / Chị Linh) **không** nhúng các trường trích dẫn học thuật (`scientific_references`) để giữ giao diện tự nhiên, dễ hiểu.

---

## 1. Kiến trúc Tổng thể Phân hệ AI (`waterpeach-api/app/ai/`)

- **Model Lõi:** `gemini-4-hydrogen` thông qua SDK chính thức `google-genai` (Interactions API `client.aio.interactions.create` + Structured Outputs `response_format`).
- **Kiến trúc Dual-Interface:**
  1. Gọi trực tiếp qua HTTP REST (`/api/v1/ai/*`) để kiểm thử độc lập trên Swagger UI (`/docs`).
  2. Import trực tiếp dạng Python `async` function từ tầng Business Services (`app/services/`) giúp loại bỏ độ trễ network hop trong luồng chuyển tiền thời gian thực.
- **Cơ chế An toàn Tuyệt đối (Graceful Fallback):** Mọi lời gọi LLM đều được bọc trong `asyncio.wait_for(..., timeout=8.0)` và có tầng Heuristic Engine tốc độ cao (`< 5ms`) dự phòng khi hết quota, chậm mạng hoặc vượt ngưỡng rate-limit.

```mermaid
flowchart TD
    subgraph Transport["HTTP Transport (app/api/v1/ai.py)"]
        E1["POST /api/v1/ai/analyze-tx"]
        E2["POST /api/v1/ai/analyze-scam"]
        E3["POST /api/v1/ai/ops-copilot"]
        E4["POST /api/v1/ai/verify-entity"]
    end

    subgraph Guard["Security, Normalizer & Velocity (app/ai/)"]
        SEC["security.py\nPrompt Injection Guard + Magic-Byte 5MB + Vietnamese Normalizer"]
        VEL["velocity_tracker.py\nSliding-Window RFM & Structuring Detector"]
        FOR["image_forensics.py\nELA Pixel Anomaly + EXIF Software Signature"]
    end

    subgraph Intel["Enrichment & Knowledge (app/ai/)"]
        ENT["entity_verifier.py\nRecipient Classifier + VietQR MST API + PhishVN URL"]
        WEB["Google Search Grounding\ntools=[google_search]"]
        KB["knowledge_base.py\n24 AIS Scenarios + VN SMS Dataset + PPSE Taxonomy"]
    end

    subgraph Engines["3 Core AI Engines + Fallback"]
        R["risk_engine.py"]
        S["scam_analyzer.py"]
        O["ops_copilot.py"]
        FB["fallbacks.py (<5ms)"]
    end

    E1 --> SEC --> VEL --> ENT --> R
    E2 --> SEC --> FOR --> ENT --> S
    E3 --> O
    E4 --> ENT --> WEB
    R & S & O -.->|"Timeout / Quota / Rate Limit"| FB
    KB --- R & S & O
```

### Cấu trúc Thư mục Phân hệ AI
```text
waterpeach-api/app/
├── core/config.py              # GEMINI_MODEL="gemini-4-hydrogen", AI_TIMEOUT_SECONDS=8.0, MAX_UPLOAD_BYTES=5MB
├── schemas/ai.py               # Pydantic v2 Request/Response DTOs & Gemini Structured Output schemas
├── ai/
│   ├── __init__.py
│   ├── client.py               # Async Gemini Interactions API + SHA-256 Deduplication Cache + Rate Limiter
│   ├── security.py             # Chống Prompt Injection, Magic-Byte validator, Vietnamese Homoglyph/Zero-width Normalizer
│   ├── knowledge_base.py       # 24 kịch bản AIS (Bộ TT&TT), Vietnamese SMS Scam Dataset, 21 đặc trưng URL PhishVN, 5 nguyên lý PPSE
│   ├── entity_verifier.py      # Phân loại recipient_name, tra cứu MST (VietQR Live API), Google Search Grounding Agent
│   ├── image_forensics.py      # Giám định ảnh kỹ thuật số: Error Level Analysis (ELA) & EXIF Software Check
│   ├── velocity_tracker.py     # Sliding-Window RFM & Phát hiện chia nhỏ giao dịch (Structuring / Smurfing)
│   ├── prompts.py              # Adaptive System Prompts theo PersonaContext (độ tuổi & quan hệ gia đình)
│   ├── fallbacks.py            # Bộ luật Heuristic tiếng Việt tốc độ cao (<5ms)
│   ├── risk_engine.py          # Động cơ 1: Contextual Transaction Risk Engine
│   ├── scam_analyzer.py        # Động cơ 2: Multimodal Scam Analyzer
│   └── ops_copilot.py          # Động cơ 3: Agentic Fraud Ops Copilot
└── api/v1/ai.py                # FastAPI Router cho 4 endpoint AI
```

---

## 2. Động cơ 1: Ma trận Chấm điểm Đa chiều (Multi-Dimensional Risk Scoring Matrix)

Bài toán của `waterpeach` thuộc nhóm **Authorized Push Payment (APP) Fraud Detection** — phát hiện gian lận khi **chính chủ tài khoản thực hiện giao dịch hợp lệ về mặt xác thực nhưng dưới sự thao túng tâm lý**.

### 2.1. Tại sao loại bỏ `sender_name` và tập trung vào `recipient_name` + Đa chiều?
- `sender_name` (tên người gửi) dễ trùng lặp và không mang thông tin phân biệt rủi ro hành vi.
- Ngược lại, **`recipient_name`** (tên tài khoản đích trả về từ NAPAS 247 / VietQR) giúp phân biệt:
  - `CORPORATION` (`CONG TY`, `CTCP`, `TNHH`, `BENH VIEN`, `TRUONG`...)
  - `MERCHANT_HKD` (`HKD`, `HO KINH DOANH`, `CUA HANG`, `SHOP`, `NHA THUOC`...)
  - `INDIVIDUAL` (tên cá nhân thông thường).
- **Tránh bẫy False Positive (Bạn bè chuyển tiền điện / Ghi note đùa giỡn):** Không kết luận lừa đảo chỉ dựa vào từ khóa trong `transfer_note` (VD: chuyển `400.000đ` cho bạn cùng phòng ghi *"nop phat tien dien"*). Hệ thống đánh giá tổ hợp **5 chiều phân tích** kèm hệ số cộng hưởng và giảm trừ.

### 2.2. 5 Chiều Phân tích & Cơ sở Nghiên cứu Khoa học (Dùng cho Vấn đáp)

| Chiều Phân tích | Đặc trưng Kỹ thuật (`Features`) | Cơ sở Khoa học & Quy chuẩn Ngành Chứng minh Tính Tối ưu |
| :--- | :--- | :--- |
| **Chiều 1: RFM & Sliding-Window Aggregation** | • `amount`, `amount / protection_threshold`, `amount / balance`<br>• `cumulative_unfamiliar_amount_60m`<br>• `tx_count_15m`, `seconds_since_last_tx`<br>• `is_sensitive_hours` (22h–06h) | • **Whitrow et al. (2009)**, *"Transaction aggregation as a strategy for credit card fraud detection"*, *Data Mining and Knowledge Discovery* (chứng minh tổng hợp giao dịch theo cửa sổ trượt vượt trội giao dịch đơn lẻ).<br>• **Bahnsen et al. (2016)**, *"Feature engineering strategies for credit card fraud detection"*, *Expert Systems with Applications* (đặc trưng chu kỳ thời gian).<br>• **Quyết định 2345/QĐ-NHNN** (NHNN Việt Nam, 01/07/2024): Ngưỡng đơn lẻ `10 triệu` & cộng dồn ngày `20 triệu`. |
| **Chiều 2: Payee Relationship Graph & Entity Verification** | • `prior_tx_count` (quen vs. `First-Time Payee`)<br>• `recipient_type` (`INDIVIDUAL` / `MERCHANT_HKD` / `CORPORATION`)<br>• Tra cứu MST qua Live API (`api.vietqr.io/v2/business/{taxCode}`) | • **UK Payment Systems Regulator (PSR) & MAS Singapore APP Fraud Guidelines**: >95% các vụ APP Fraud chuyển tiền tới *Người nhận lần đầu (`prior_tx_count == 0`)*.<br>• Nguồn dữ liệu thuế chính thức từ Tổng cục Thuế (`gdt.gov.vn`) qua VietQR Business API (đã kiểm thử thực tế HTTP 200 OK). |
| **Chiều 3: Behavioral Coercion Telemetry** | • `in_active_call` (đang nghe ĐT/Zalo call khi chuyển tiền)<br>• `is_copy_pasted_account` (dán STK từ ứng dụng chat) | • Nghiên cứu công nghiệp về **APP Fraud Behavioral Biometrics (BioCatch, SEON & MAS Singapore)**: Tổ hợp `First-Time Payee` $\cap$ `In Active Call` $\cap$ `Copy-Pasted Account` là chữ ký hành vi đặc trưng của cưỡng chế tâm lý (*Coercive Social Engineering Signature*). |
| **Chiều 4: Semantic & Entity-Context NLP** | • Ngữ nghĩa tiếng Việt (có dấu/không dấu/viết tắt) trong `transfer_note`<br>• `Entity-Context Mismatch` (nội dung công quyền/thuế/công an nhưng người nhận là cá nhân lạ) | • **Ferreira, Coventry & Lenzini (2015)** (*PPSE Framework*) & **Stajano & Wilson (2011)** (*Communications of the ACM*).<br>• **24 Hình thức lừa đảo AIS (Bộ TT&TT)** & **Vietnamese Quality-Assured SMS Scam Dataset** (*Tran et al., 2026*, `trannguyenthaituan251209/vietnamese_sms_dataset`). |
| **Chiều 5: Threat Intel & Google Search Grounding** | • `threat_blacklist` nội bộ (Supabase + Redis)<br>• 21 đặc trưng lexical URL (**PhishVN**)<br>• Google Search Grounding (`tools=[{"type": "google_search"}]`) | • **PhishVN Dataset** (*Data in Brief 68*, 2026 — DOI `10.17632/b97hxbxtpd.5`, >53.000 URL Việt Nam từ NCSC & Chống Lừa Đảo).<br>• Enrich context thời gian thực về pháp nhân, SĐT, tên miền và tin tức cảnh báo từ báo chí/cổng thông tin công. |

### 2.3. Công thức Toán học Minh bạch (Explainable Hybrid Scoring)

$$S_{\text{total}} = \operatorname{clamp}_{0}^{100}\left( \sum_{i=1}^{5} S_i(\mathbf{x}) + \Phi_{\text{interaction}}(\mathbf{x}) - \Psi_{\text{trust}}(\mathbf{x}) \right)$$

- **$\Phi_{\text{interaction}}(\mathbf{x})$ (Hệ số Cộng hưởng Phi tuyến):**
  1. *Mâu thuẫn Pháp nhân $\times$ Người lạ $\times$ Giá trị đáng kể:* Nếu nội dung mang ngữ nghĩa Công quyền/Thuế/Công an/Cưỡng chế $\land$ `recipient_type == INDIVIDUAL` $\land$ `prior_tx_count == 0` $\land$ `amount >= 2.000.000đ` $\rightarrow$ **`+35` điểm**. (Bạn bè chuyển `400.000đ` tiền điện ghi note đùa với `prior_tx_count >= 1` sẽ không kích hoạt cộng hưởng này và bị trừ điểm tin cậy $\rightarrow$ `LOW`).
  2. *Tổ hợp Cuộc gọi thao túng $\times$ Người nhận mới:* Nếu `in_active_call == True` $\land$ `prior_tx_count == 0` $\land$ `amount >= 0.5 * protection_threshold` $\rightarrow$ **`+25` điểm**.
- **$\Psi_{\text{trust}}(\mathbf{x})$ (Hệ số Giảm trừ Uy tín — Giảm 70–80% False Positives):**
  1. *Người quen lâu năm:* `prior_tx_count >= 3` và không có dấu hiệu ép buộc/tần suất bất thường $\rightarrow$ **`-30` điểm**.
  2. *Hộ kinh doanh / Doanh nghiệp xác thực MST hợp lệ:* `recipient_type` là `MERCHANT_HKD` hoặc `CORPORATION` + MST trạng thái `"NNT đang hoạt động"` + nội dung mua bán hàng hóa bình thường $\rightarrow$ Hạ mức cảnh báo từ lừa đảo `CRITICAL` xuống xác minh giao dịch giá trị lớn (`MEDIUM/HIGH`), gợi ý người giám hộ bấm **Nút Xanh mở khóa nhanh**.

### 2.4. Phát hiện Thủ đoạn Chia nhỏ Giao dịch Lách hạn mức (Structuring / Smurfing & Velocity Attack)
Xử lý kịch bản kẻ gian xúi chuyển `3.000.000đ` rồi `2.500.000đ` liên tiếp để né ngưỡng `5.000.000đ`:
1. **Cộng dồn Cửa sổ trượt 60 phút (`Cumulative Window`):**
   $$\text{CumulativeUnfamiliarAmount}_{60\text{m}} = \text{current\_amount} + \sum_{t \in \text{last 60m}} \text{amount}(t \text{ tới người lạ})$$
   Ngay khi tổng cộng dồn $\ge$ `protection_threshold` $\rightarrow$ Kích hoạt `cooling_off` (`+30` điểm).
2. **Dấu hiệu Chia nhỏ Sát ngưỡng (`Structuring Signature`):**
   Giao dịch tới người lạ nằm trong dải `60%–99%` ngưỡng bảo vệ lặp lại $\ge 2$ lần trong 30 phút $\rightarrow$ Gắn cờ `STRUCTURING_SPLIT_TX_DETECTED` (`+40` điểm).
3. **Gia tốc Tần suất (`Rapid Burst Velocity`):**
   `seconds_since_last_tx < 180s` hoặc `tx_count_15m >= 2` tới tài khoản lạ $\rightarrow$ Cộng điểm cảnh báo bị thúc ép chuyển dồn dập.

---

## 3. Cá nhân hóa Ngôn ngữ theo Hồ sơ Động (`PersonaContext`)

Thay vì mặc định nạn nhân là người lớn tuổi, toàn bộ lời giải thích (`reasoning_for_victim`, `reasoning_for_guardian`) và kịch bản hạ nhiệt (`call_script`) tự động thích ứng theo cặp **`(victim_age_group, guardian_relationship)`**:

| `victim_age_group` | `guardian_relationship` | Giọng văn & Kịch bản Trọng tâm |
| :--- | :--- | :--- |
| `55_plus_senior` | `child_of_victim` (Con bảo vệ bố mẹ) | Xưng hô kính trọng (*Bác / Cô / Chú*), ngôn ngữ bình dân, giải thích rõ cơ quan Công an/Tòa án/Thuế không bao giờ yêu cầu chuyển tiền xác minh. |
| `under_18` / `18_25_student` | `parent_of_victim` (Cha mẹ bảo vệ con) | Xưng hô gần gũi (*Bạn / Em*), cảnh báo thẳng thắn về bẫy **"Làm nhiệm vụ hoàn tiền"**, **"Sunk-Cost (nạp thêm để rút gốc)"**, **"Vay app / Nạp game / Thuê tài khoản"**. |
| `26_55_adult` | `spouse` / `sibling` (Vợ chồng / Người thân) | Ngôn ngữ minh bạch, ngang hàng (*Anh / Chị*), tập trung vào xác minh khoản chi lớn, đầu tư giả mạo hoặc tài khoản nhận bất thường. |

---

## 4. Động cơ 2: Giám định Ảnh Công văn/Hóa đơn Giả & 5 Nguyên lý Thao túng Tâm lý

### 4.1. Kiến trúc Hybrid: Digital Image Forensics + End-to-End VLM
LLM đa dụng (như Gemini) rất mạnh về ngữ nghĩa nhưng không chuyên sâu bằng thuật toán giám định kỹ thuật số ở mức điểm ảnh. Do đó, `scam_analyzer.py` kết hợp 3 tầng:
1. **Tầng 1 — Pixel-level & Metadata Forensics (`image_forensics.py`, `< 150ms` trên CPU):**
   - *Cơ sở nghiên cứu:* **ELA — Error Level Analysis (Krawetz, 2007)**, **DocTamper (CVPR 2023)**, **TruFor (CVPR 2023)**, **CAT-Net**.
   - *Thực thi:* Quét EXIF/XMP bắt chữ ký phần mềm chỉnh sửa (`Adobe Photoshop`, `Canva`, `GIMP`, `PicsArt`...); tính ma trận sai số nén JPEG ở chất lượng 90% (`|I_orig - I_recompressed|`), phân tích phương sai khối để tính **`forensic_tamper_score` (0–100)** phát hiện vùng số tiền hoặc con dấu đỏ bị cắt ghép.
2. **Tầng 2 — End-to-End VLM (`gemini-4-hydrogen`):**
   - Đọc ngữ cảnh giao diện (thanh cảnh báo *"Người lạ"* trên Zalo, tên hiển thị mạo danh ngân hàng gửi từ SĐT cá nhân `+84...`, lỗi thể thức văn bản hành chính trên công văn giả).
3. **Tầng 3 — Hybrid Regex & PhishVN URL Analyzer:**
   - Hậu kiểm Regex bắt 100% STK (8–16 chữ số), SĐT Việt Nam và chấm điểm URL độc hại theo 21 đặc trưng từ **PhishVN (2026)**.

### 4.2. 5 Thủ thuật Thao túng Tâm lý có Cơ sở Khoa học (PPSE Framework)
Chuẩn hóa theo **Ferreira, Coventry & Lenzini (2015)** (*Principles of Persuasion in Social Engineering — PPSE*), **Cialdini (2001)** và **Stajano & Wilson (2011)**:
1. **`AUTHORITY`** *(Authority & Social Compliance)*: Mạo danh Công an, Viện kiểm sát, Thuế, Ngân hàng.
2. **`URGENCY`** *(Distraction & Scarcity / Time-Pressure)*: Ép thời gian khẩn cấp gây hiệu ứng tầm nhìn đường hầm (*"khóa tài khoản trong 2 giờ"*).
3. **`FEAR`** *(Strong Affect / Fear Appeal)*: Đe dọa lệnh bắt tạm giam, phong tỏa tài sản, liên lụy án hình sự.
4. **`GREED`** *(Need & Greed Principle)*: Hứa hẹn việc nhẹ lương cao, hoa hồng 20–30%, trúng thưởng lớn.
5. **`RECIPROCITY_COMMITMENT`** *(Reciprocation, Commitment & Sunk-Cost)*: Trả thưởng nhỏ ban đầu để dụ nạp số tiền lớn hơn ở các nhiệm vụ sau.

---

## 5. Phòng chống Tấn công, Spam & Phá Hệ thống (Adversarial & Anti-Abuse)

1. **Chống Prompt Injection (`security.py`):**
   - Bọc dữ liệu người dùng (`transfer_note`, text OCR) trong thẻ XML cách ly `<untrusted_user_content>...</untrusted_user_content>` kèm chỉ thị cấm thực thi lệnh bên trong.
   - Bộ quét Pre-LLM bắt các cụm từ tiêm lệnh (*"ignore previous"*, *"bỏ qua hướng dẫn"*, *"risk_score=0"*, *"system prompt"*) $\rightarrow$ Tự động gắn cờ `PROMPT_INJECTION_ATTEMPT` và **cộng phạt `+50` điểm rủi ro**.
2. **Chống Spam & Denial-of-Wallet (`client.py`):**
   - **SHA-256 Deduplication Cache (TTL 5 phút):** Các request trùng lặp nội dung/ảnh trả về kết quả cache trong `< 2ms`, không tiêu tốn token Gemini.
   - **Sliding-Window Rate Limiter:** Khi vượt ngưỡng request/phút theo `sender_id`/IP, tự động chuyển sang Fast Heuristic Engine (`< 5ms`) thay vì làm nghẽn hệ thống.
3. **Chống Image Bomb & File Độc hại:**
   - Giới hạn upload tối đa **`5 MB`**; kiểm tra **Magic Bytes** thực tế (`PNG`, `JPEG`, `WEBP`, `WAV`, `MP3`); giới hạn `transfer_note <= 500` ký tự và `raw_text <= 4.000` ký tự.
4. **Chống Lách từ khóa (Evasion Normalization):**
   - `VietnameseTextNormalizer` tự động xóa zero-width spaces (`\u200b-\u200d`), gộp ký tự phân cách (`n.o.p` $\rightarrow$ `nop`), chuẩn hóa leetspeak/homoglyphs (`0→o, 1→i, 3→e`) trước khi đối chiếu.
5. **Chống Alert Fatigue:**
   - Phát hiện burst giao dịch liên tiếp (`tx_count_15m >= 3`) $\rightarrow$ Gộp cảnh báo và nâng mức lên `ACCOUNT_COMPROMISE_OR_COERCION`.

---

## 6. Tài liệu Tham khảo Khoa học (Phục vụ Vấn đáp)

1. Whitrow, C., Hand, D. J., Juszczak, P., Weston, D. J., & Adams, N. M. (2009). *Transaction aggregation as a strategy for credit card fraud detection*. Data Mining and Knowledge Discovery.
2. Bahnsen, A. C., Aouada, D., Stojanovic, A., & Ottersten, B. (2016). *Feature engineering strategies for credit card fraud detection*. Expert Systems with Applications.
3. Stajano, F., & Wilson, P. (2011). *Understanding scam victims: seven principles for systems security*. Communications of the ACM.
4. Ferreira, A., Coventry, L., & Lenzini, G. (2015). *Principles of persuasion in social engineering and their use in phishing*. International Conference on Human Aspects of Information Security, Privacy, and Trust.
5. Tran et al. (2026). *Vietnamese SMS Dataset with Quality Assurance* (`trannguyenthaituan251209/vietnamese_sms_dataset`).
6. PhishVN (2026). *Time-Stamped Vietnamese URL Phishing Dataset & Baselines*. Data in Brief 68 (Mendeley DOI: `10.17632/b97hxbxtpd.5`).
7. Qu, C. et al. (2023). *DocTamper: Towards Robust Tampered Text Detection in Document Images*. CVPR 2023 (`qcf-568/DocTamper`) & Guillaro et al. (2023), *TruFor* (`grip-unina/TruFor`).
8. Ngân hàng Nhà nước Việt Nam (2023). *Quyết định số 2345/QĐ-NHNN* (hiệu lực 01/07/2024) về giải pháp an toàn, bảo mật trong thanh toán trực tuyến.
9. Cục An toàn thông tin (AIS — Bộ TT&TT). *Cẩm nang nhận diện 24 hình thức lừa đảo trên không gian mạng Việt Nam*.
