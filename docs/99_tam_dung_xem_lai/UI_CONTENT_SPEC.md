# UI Content Specification — DNC Video Surveillance System (VSS)

> Tài liệu này mô tả **toàn bộ nội dung** hiển thị trong UI hiện tại.
> Mục đích: làm tài liệu tham chiếu khi thiết kế lại giao diện trên Claudesign / Framer.
> Không chứa code — chỉ mô tả nội dung, luồng và dữ liệu.

---

## 1. Thông tin chung

| Trường | Giá trị |
|---|---|
| Tên app | **DNC - VSS** (Video Surveillance System) |
| Page title | `DNC - VSS` |
| Layout | Wide (full-width) |
| Ngôn ngữ | Tiếng Việt (UI), Tiếng Anh (data fields) |
| Logo | `logo.svg` hoặc `logo.png` (hiển thị ở sidebar và header) |

---

## 2. Cấu trúc tổng thể

```
┌─────────────────────────────────────────────────┐
│  SIDEBAR (navigation + settings)                │
│  └── Logo                                       │
│  └── Menu điều hướng (4 mục)                    │
│  └── Cấu hình LLM (collapsible)                 │
├─────────────────────────────────────────────────┤
│  MAIN CONTENT (thay đổi theo menu)              │
│  ├── [Trang 1] Upload Video / Xem kết quả       │
│  ├── [Trang 2] Tìm kiếm toàn lịch sử           │
│  ├── [Trang 3] Lịch sử phân tích               │
│  └── [Trang 4] Báo cáo & Xuất file             │
└─────────────────────────────────────────────────┘
```

---

## 3. SIDEBAR

### 3.1 Logo
- Hiển thị logo ở đầu sidebar
- File: `logo.svg` (ưu tiên) hoặc `logo.png`

### 3.2 Menu điều hướng
Dạng radio button, chọn 1 trong 4 mục:

| STT | Nhãn menu | Chức năng |
|---|---|---|
| 1 | Upload Video Mới | Xem/upload video và kết quả phân tích |
| 2 | Tìm Kiếm Toàn Lịch Sử | Tìm kiếm ngữ nghĩa trên tất cả video đã lưu |
| 3 | Lịch Sử Phân Tích | Danh sách video đã phân tích |
| 4 | Báo Cáo & Xuất File | Cấu hình và xuất báo cáo |

### 3.3 Cấu hình LLM (collapsible, mặc định đóng)
**Tiêu đề:** "Cấu hình LLM metadata"

| Input | Loại | Mô tả |
|---|---|---|
| API Key | Password input | Key cho endpoint OpenAI-compatible |
| Base URL | Text input | URL endpoint LLM |
| Model metadata | Text input | Tên model dùng cho metadata search |
| Nút "Lưu cấu hình LLM" | Button | Lưu vào `config.json` |

---

## 4. TRANG 1 — Upload Video & Xem kết quả

### 4.1 Header trang
- **Logo** (nhỏ, bên trái)
- **Tiêu đề lớn:** `DNC - Video Surveillance System`
- **Mô tả:** `Phân tích video giám sát, tóm tắt nội dung và tìm kiếm phân đoạn bằng ngôn ngữ tự nhiên`
- Nền gradient xanh teal nhạt

### 4.2 Trạng thái A — Chưa có kết quả phân tích
Chỉ hiển thị panel chọn video (xem mục 4.4).

### 4.3 Trạng thái B — Đã có kết quả phân tích
Layout 3 cột: **Video | Timeline | Search/Filter**

#### Cột trái — Video đầu vào (tỷ lệ 1.6)
- **Tiêu đề section:** "Video đầu vào"
- **Video player** (Streamlit native `st.video`)
  - Tự động nhảy đến thời điểm của phân đoạn đang chọn
- **Info card phân đoạn đang xem** (nền xanh teal nhạt):
  - `#[số thứ tự] · [giờ:phút:giây bắt đầu] → [giờ:phút:giây kết thúc]`
  - Mô tả nội dung phân đoạn (text)
- Nếu chưa chọn phân đoạn: hiển thị caption "Chưa có phân đoạn nào được chọn."

#### Cột giữa — Timeline (tỷ lệ 1.2)
- **Tiêu đề section:** "Timeline"
- **Counter:** `[X]/[Tổng] đoạn` (số đoạn sau lọc / tổng)
- **Danh sách phân đoạn** (scrollable, chiều cao cố định):
  Mỗi item hiển thị:
  - Icon trạng thái: ✅ (đã xác thực) hoặc ⚠️ (chưa xác thực) hoặc trống
  - `#[số] · [giờ bắt đầu] → [giờ kết thúc]`
  - Badge rủi ro: `NONE` / `LOW` / `MEDIUM` / `HIGH` (màu tương ứng)
  - Mô tả phân đoạn (tối đa 140 ký tự)
  - Badges hành động phát hiện (nếu có): 📱 Điện thoại / 🚶 Rởi bàn / 👥 Tụ tập
  - Nút **"Xem"** → nhảy video đến thời điểm đó và highlight item
  - Trạng thái active (đang chọn) có border trái xanh đậm
  - Trạng thái validated: border trái xanh lá
  - Trạng thái unvalidated: border trái vàng

#### Cột phải — Search, Filter, Chat (tỷ lệ 0.9)
Gồm 5 panel xếp dọc:

**Panel 1 — Xác thực kết quả**
- Tiêu đề: "✅ Xác thực kết quả"
- 3 metric cards:
  - **Tổng**: tổng số phân đoạn
  - **Đã xác thực**: số đoạn có nhận diện được hành động + % / tổng
  - **Chưa xác thực**: số đoạn chưa nhận diện + % / tổng
- Breakdown hành động (nếu có xác thực):
  - 📱 Điện thoại: [số]
  - 🚶 Rởi bàn: [số]
  - 👥 Tụ tập: [số]

**Panel 2 — Tìm kiếm**
- Tiêu đề: "🔍 Tìm kiếm"
- **Ô nhập câu hỏi** (textarea, placeholder: "đoạn nào có nhiều người tụ tập hoặc dùng điện thoại")
- **Slider số kết quả**: 3–20, mặc định 8
- **Dropdown chế độ**:
  - `Vector` (Hybrid LanceDB)
  - `LLM` (LLM trên metadata)
- **Nút "Tìm"** (primary)
- Hiển thị kết quả tìm kiếm (text tóm tắt từ AI) nếu có

**Panel 3 — Lọc nhanh**
- Tiêu đề: "🎯 Lọc nhanh"
- **Multiselect hành động**:
  - Cầm điện thoại
  - Rởi khỏi bàn làm việc
  - Tụ tập đông người
- **Checkbox "Hôm nay"**: chỉ hiện phân đoạn hôm nay
- **Date picker Từ ngày** / **Đến ngày**
- **Checkbox "Chỉ kết quả xác thực"**
- Caption: `🎯 [X]/[Tổng] đoạn phù hợp` (nếu có filter đang áp dụng)

**Panel 4 — AI Chat**
- Tiêu đề: "💬 AI Chat"
- Khung chat (chiều cao 200px):
  - Hiển thị lịch sử hội thoại (user / assistant messages)
  - Caption "Đặt câu hỏi để chat với AI." nếu chưa có lịch sử
- Ô nhập chat (`chat_input`, placeholder: "Hỏi AI...")
- Lưu ý: AI chat hiện chỉ echo lại input và hiển thị kết quả tìm kiếm gần nhất

**Panel 5 — Đặt lại**
- Tiêu đề: "🔄 Đặt lại"
- Collapsible "Chọn mức độ xóa":
  - Cảnh báo: "⚠️ Thao tác không thể hoàn tác!"
  - Nút **1️⃣ Reset session (dữ liệu tạm)**: xóa session state
  - Nút **2️⃣ Xóa file video & kết quả phân tích**: xóa file outputs
  - Nút **3️⃣ Xóa toàn bộ + Database** (danger): xóa file + vector DB

### 4.4 Panel chọn video & phân tích (hiển thị ở cả 2 trạng thái)
Layout 3 cột:

**Cột 1 — Upload video**
- Nhãn: "Upload video"
- File uploader: chỉ chấp nhận `.mp4`
- Sau upload: hiển thị toast "✅ Đã upload: [tên file] ([kích thước])"

**Cột 2 — Chọn từ server**
- Nhãn: "Hoặc chọn từ server"
- Dropdown danh sách video trong thư mục server: `[tên file] ([kích thước])`
- Nút **"Sử dụng"** để chọn video từ server
- Nếu không có video: caption "Không có video trong thư mục server"

**Cột 3 — Hành động**
- Nhãn: "Hành động"
- Nút **"Bắt đầu phân tích"** (primary, lần đầu) hoặc **"Phân tích lại"** (khi đã có kết quả)
- Nếu chưa có video hợp lệ: warning "Chưa có video hợp lệ"
- Nếu đã có kết quả và bấm phân tích lại → hiện dialog xác nhận (xem 4.5)

**Thông tin video hiện tại** (dưới 3 cột):
- `✅ [tên file] · [kích thước]`

**Thiết lập đường dẫn folder input** (collapsible):
- Text input đường dẫn thư mục
- Nút **"Lưu đường dẫn"**
- Nút **"Mở thư mục"** (mở Windows Explorer)
- Caption đường dẫn hiện tại

### 4.5 Dialog xác nhận phân tích lại
**Tiêu đề dialog:** "⚠️ Xác nhận phân tích lại"

Nội dung:
- Warning: "Video này đã được phân tích trước đó."
- Danh sách hệ quả:
  - ❌ Xóa kết quả phân tích cũ
  - ❌ Xóa dữ liệu vector DB liên quan
  - ❌ Xóa file chunks đã tạo
  - ✅ Phân tích lại từ đầu
- Nút **"Hủy"**
- Nút **"✅ Đồng ý phân tích lại"** (primary)

---

## 5. TRANG 2 — Tìm kiếm toàn lịch sử

**Tiêu đề trang:** "Tìm kiếm trên toàn bộ lịch sử video"

### Inputs
| Input | Loại | Mô tả |
|---|---|---|
| Câu hỏi | Textarea (90px) | Ví dụ: "đoạn nào có nhiều người tụ tập hoặc sử dụng điện thoại" |
| Số đoạn trả về | Slider (3–30, mặc định 10) | Số lượng kết quả |
| Chế độ tìm kiếm | Radio button | Hybrid LanceDB (vector + metadata) / LLM trên metadata |

### Actions
| Nút | Mô tả |
|---|---|
| **"Tìm trên lịch sử"** (primary) | Chạy tìm kiếm, hiển thị kết quả |
| **"Lập chỉ mục lại toàn bộ lịch sử"** | Rebuild vector index, hiển thị số segment đã index |

### Kết quả tìm kiếm
- Text tóm tắt từ AI (info box)
- Bảng danh sách kết quả (dạng hàng), mỗi hàng:

| Cột | Nội dung |
|---|---|
| Video ID | Tên/ID video (nút bấm → mở dialog xem chi tiết) |
| Bắt đầu | Thời điểm bắt đầu (`HH:MM:SS`) |
| Kết thúc | Thời điểm kết thúc (`HH:MM:SS`) |
| Rủi ro | `none` / `low` / `medium` / `high` |
| Chú thích | Mô tả nội dung phân đoạn |

### Dialog xem kết quả video
**Tiêu đề:** "Xem kết quả video"

Nội dung:
- **Video ID:** `[id]`
- `[giờ bắt đầu] → [giờ kết thúc]` | Rủi ro: [mức]
- Mô tả nội dung phân đoạn
- **Video chunk** (clip ngắn) nếu có file chunk
- Hoặc **Video gốc** bắt đầu từ đúng thời điểm nếu không có chunk
- Warning "Không tìm thấy file video" nếu cả hai đều không có
- Expander "Xem video gốc" nếu có cả hai

---

## 6. TRANG 3 — Lịch sử phân tích

**Tiêu đề trang:** "Danh sách video đã phân tích"

Danh sách các video đã phân tích, mỗi item hiển thị 2 cột:

**Cột thông tin (cột trái):**
- **Video ID** (bold)
- Caption: `[đường dẫn file] | segments: [số đoạn]`
- Tóm tắt nội dung (tối đa 280 ký tự)

**Cột hành động (cột phải):**
- Nút **"Xem chi tiết"** → mở dialog

### Dialog chi tiết video đã phân tích
**Tiêu đề:** "Chi tiết video đã phân tích"

Nội dung:
- **Video ID:** `[id]`
- Caption: đường dẫn file video
- **Bảng dữ liệu** tất cả phân đoạn:

| Cột | Nội dung |
|---|---|
| Bắt đầu | `HH:MM:SS` |
| Kết thúc | `HH:MM:SS` |
| Rủi ro | `none` / `low` / `medium` / `high` |
| Chú thích | Mô tả phân đoạn |

- **Preview phân đoạn** (tối đa 12 đoạn đầu):
  - `#[số] [giờ bắt đầu] -> [giờ kết thúc]: [mô tả]`
  - Video player cho chunk tương ứng (nếu có file)

---

## 7. TRANG 4 — Báo cáo & Xuất file

4 sub-tab bên trong:

### Tab 1 — Cấu hình Template báo cáo
**Tiêu đề:** "Cấu hình Template Báo cáo"

| Input | Loại | Giá trị mặc định |
|---|---|---|
| Tiêu đề báo cáo | Text input | `BÁO CÁO GIÁM SÁT VIDEO` |
| Nội dung đầu trang (header) | Textarea | `HỆ THỐNG GIÁM SÁT AN NINH\nCông ty DNC` |
| Nội dung cuối trang (footer) | Textarea | `Người lập báo cáo: ___\nNgày lập: {date}` |
| Thống kê hành động | Checkbox | ✅ bật |
| Danh sách sự kiện | Checkbox | ✅ bật |
| Chi tiết mô tả | Checkbox | ✅ bật |

- Tự động lưu vào `config.json` khi thay đổi
- Hiển thị "✅ Template đã được lưu tự động."

### Tab 2 — Cấu hình Email
**Tiêu đề:** "Cấu hình Gửi Email Báo cáo"

**Thông tin đang lưu (hiển thị):**
- Server / Port / SSL
- Sender email / Recipients / Trạng thái mật khẩu

**Inputs cấu hình:**
| Input | Loại | Mặc định |
|---|---|---|
| SMTP Server | Text | `smtp.gmail.com` |
| SMTP Port | Number | `587` |
| Email gửi (sender) | Text | — |
| Mật khẩu ứng dụng (App Password) | Password | — |
| Bật SSL/TLS (STARTTLS) | Checkbox | ✅ |
| Email nhận (phân cách bằng dấu phẩy) | Textarea | — |

**Thông báo tự động khi phát hiện rủi ro:**
- Dropdown ngưỡng rủi ro: `Thấp (low) trở lên` / `Trung bình (medium) trở lên` / `Cao (high)`
- Ghi chú: "Với Gmail, cần tạo App Password"

**Buttons:**
- **"💾 Lưu cấu hình"** (primary)
- **"🔄 Mặc định Gmail"**

### Tab 3 — Thư mục Input
**Tiêu đề:** "Thư mục Input mặc định"

**Thông tin:**
- Path hiện tại (hiển thị)

**Inputs:**
- Text input đường dẫn thư mục
- Nút **"📂 Browse"** → mở file dialog chọn thư mục

**Buttons:**
- **"💾 Lưu path"** (primary)
- **"🔄 Mặc định"**
- **"📂 Mở thư mục"**

---

**Giám sát thư mục tự động:**
- Toggle **"Bật giám sát tự động"**
- Khi đang chạy, hiển thị:

| Thông tin | Mô tả |
|---|---|
| Trạng thái (stage) | idle / waiting / model_loading / chunking / analyzing / summarizing / indexing / alerting / completed / error |
| Thư mục đang giám sát | Đường dẫn |
| File đang xử lý | Tên file |
| Thời gian video | `MM:SS` và kích thước |
| Thời gian đã chạy | Số giây |
| Progress bar chunks | `Chunk X/Y (Z%)` |
| Phân loại rủi ro | 🔴 Cao: [số] | 🟡 Trung bình: [số] | 🟢 Thấp: [số] |
| Thống kê | Đã xử lý: X | Bỏ qua: Y | Lỗi: Z |
| Log gần nhất | Dòng log cuối |

- Khi tắt: info "🔴 Giám sát đang tắt. Bật toggle để tự động phân tích..."

---

**Gửi email cảnh báo tự động:**
- Toggle **"Bật gửi email cảnh báo rủi ro"**
- Điều kiện: phải cấu hình SMTP đầy đủ trước

### Tab 4 — Xuất báo cáo
**Tiêu đề:** "Xuất Báo cáo"

**Filters:**
| Filter | Loại | Tùy chọn |
|---|---|---|
| Thời gian | Dropdown | Hôm nay / Tùy chỉnh / Tất cả |
| Hành động | Multiselect | Cầm điện thoại / Rởi khỏi bàn làm việc / Tụ tập đông người |
| Định dạng xuất | Dropdown | Excel (.xlsx) / PDF (.pdf) / HTML (.html) |

- Nếu chọn "Tùy chỉnh": hiện thêm Date picker "Từ ngày" và "Đến ngày"
- Caption: `📋 [X] sự kiện sẽ được xuất`

**Buttons:**
- **"📥 Tạo & Tải báo cáo"** (primary): download file
- **"📧 Gửi Email báo cáo"** (primary): gửi email kèm file đính kèm
- Caption email nhận (hoặc cảnh báo chưa cấu hình)

---

## 8. Data model — Phân đoạn video (Event/Segment)

Mỗi phân đoạn video chứa các trường sau, UI cần hiển thị:

| Trường | Kiểu | Mô tả |
|---|---|---|
| `start` | String | Thời điểm bắt đầu, format `HH:MM:SS` |
| `end` | String | Thời điểm kết thúc, format `HH:MM:SS` |
| `sec` | Number | Giây bắt đầu (dùng để seek video) |
| `desc` | String | Mô tả nội dung phân đoạn (do AI tạo) |
| `risk_level` | String | `none` / `low` / `medium` / `high` |
| `abnormal` | Boolean | Có bất thường hay không |
| `chunk_path` | String | Đường dẫn file video clip ngắn của phân đoạn |
| `video_file` | String | Đường dẫn file video gốc |
| `video_id` | String | ID định danh video |

**Hành động tự động phát hiện từ `desc`:**
| Hành động | Key | Icon |
|---|---|---|
| Cầm/dùng điện thoại | `phone` | 📱 |
| Rởi khỏi bàn làm việc | `leave_desk` | 🚶 |
| Tụ tập đông người | `crowd` | 👥 |

---

## 9. Data model — Video tóm tắt (Summary)

| Trường | Mô tả |
|---|---|
| `overview` | Tóm tắt tổng quan nội dung video (text dài) |
| `meaning` | Ý nghĩa / kết luận từ video |

Hiển thị trong sidebar (khi mở tab Video) dưới dạng card nền xanh teal nhạt.

---

## 10. Thống kê tổng quan (Metrics)

Hiện trong sidebar khi đang xem kết quả phân tích:

| Metric | Mô tả |
|---|---|
| Tổng đoạn | Tổng số phân đoạn trong video |
| Bất thường | Số phân đoạn có `abnormal = true` |
| Rủi ro cao | Số phân đoạn có `risk_level = "high"` |
| Đã index | "Có" / "Không" — vector index đã được tạo chưa |

---

## 11. Luồng người dùng chính

### Luồng A — Phân tích video mới
1. Vào trang "Upload Video Mới"
2. Upload file `.mp4` **hoặc** chọn từ server
3. Nhấn "Bắt đầu phân tích" → spinner trong khi xử lý
4. Sau khi xong → tự động chuyển sang view kết quả
5. Xem video + timeline phân đoạn
6. Tùy chọn: tìm kiếm / lọc / chat với AI

### Luồng B — Tìm kiếm trong video hiện tại
1. Nhập câu hỏi vào ô tìm kiếm (cột phải)
2. Chọn chế độ (Vector / LLM), số kết quả
3. Nhấn "Tìm" → timeline cập nhật, AI trả lời
4. Bấm "Xem" trên timeline item → video nhảy đến đúng phân đoạn

### Luồng C — Tìm kiếm lịch sử
1. Vào "Tìm Kiếm Toàn Lịch Sử"
2. Nhập câu hỏi, chọn chế độ và số kết quả
3. Nhấn "Tìm trên lịch sử"
4. Xem bảng kết quả, bấm Video ID → xem clip/video tại thời điểm đó

### Luồng D — Xuất báo cáo
1. Vào "Báo Cáo & Xuất File"
2. (Tùy chọn) Cấu hình template và email ở các tab tương ứng
3. Vào tab "Xuất Báo cáo"
4. Chọn bộ lọc thời gian, hành động, định dạng
5. Nhấn "Tạo & Tải báo cáo" hoặc "Gửi Email báo cáo"

### Luồng E — Giám sát thư mục tự động
1. Vào "Báo Cáo & Xuất File" → tab "Thư mục Input"
2. Nhập/lưu đường dẫn thư mục chứa video
3. (Tùy chọn) Cấu hình email cảnh báo ở tab "Cấu hình Email"
4. Bật toggle "Giám sát tự động"
5. Hệ thống tự động phát hiện file mới và phân tích, gửi email cảnh báo nếu phát hiện rủi ro

---

## 12. Trạng thái giám sát tự động (Monitor Stages)

| Stage | Nhãn hiển thị |
|---|---|
| `idle` | 🟢 Đang chạy |
| `waiting` | ⏳ Chờ file |
| `model_loading` | 🧠 Nạp model |
| `chunking` | ✂️ Cắt chunk |
| `analyzing` | 🔍 Phân tích |
| `summarizing` | 📝 Tóm tắt |
| `indexing` | 📇 Index |
| `alerting` | 📧 Gửi cảnh báo |
| `completed` | ✅ Hoàn tất |
| `error` | ❌ Lỗi |

---

## 13. Báo cáo xuất file

### Định dạng hỗ trợ
| Định dạng | Extension | Nội dung |
|---|---|---|
| Excel | `.xlsx` | Bảng sự kiện + thống kê theo sheet |
| PDF | `.pdf` | Báo cáo có header/footer tùy chỉnh |
| HTML | `.html` | Trang web có thể mở bằng browser |

### Nội dung báo cáo (tùy theo checkbox đã chọn)
- **Header**: tên tổ chức, tiêu đề báo cáo
- **Thống kê hành động**: số lần phát hiện phone / leave_desk / crowd
- **Danh sách sự kiện**: bảng các phân đoạn
- **Chi tiết mô tả**: mô tả đầy đủ từng phân đoạn
- **Footer**: người lập, ngày lập

### Email gửi kèm báo cáo
- Subject: `[BÁO CÁO DNC-VSS #YYYYMMDDHHMMSS] [Tiêu đề] – [Khoảng thời gian] – Gửi lúc HH:MM`
- Body HTML: tóm tắt số liệu + file đính kèm
- Attachment: file xuất theo định dạng đã chọn

---

## 14. Ghi chú cho thiết kế mới

### Nội dung BẮT BUỘC phải có (critical)
- Video player với khả năng seek đến timestamp cụ thể
- Danh sách phân đoạn dạng timeline (scrollable)
- Ô tìm kiếm ngữ nghĩa
- 4 mục navigation chính
- Panel thống kê (Tổng / Bất thường / Rủi ro cao / Đã index)

### Nội dung có thể đơn giản hóa
- AI Chat: hiện chỉ echo input + kết quả search gần nhất, không phải real AI chat
- Panel "Đặt lại": có thể ẩn vào settings/admin
- Cấu hình LLM sidebar: có thể chuyển vào trang settings riêng

### Nội dung có thể ẩn vào settings/admin (không cần trên main UI)
- Cấu hình SMTP email
- Cấu hình đường dẫn thư mục input
- Cấu hình template báo cáo
- Cấu hình API key / Base URL / Model name

### Dữ liệu thực tế có thể thiếu
- `chunk_path`: không phải lúc nào cũng có file clip ngắn → UI phải fallback về video gốc
- `video_file`: có thể là WSL path, cần convert → hiển thị "Không tìm thấy" nếu không resolve được
- `video_summary`: có thể rỗng nếu AI không tóm tắt được
- `risk_level`: mặc định `none` nếu không phân tích được rủi ro
