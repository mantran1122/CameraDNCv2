# BÁO CÁO PHÂN TÍCH HỆ THỐNG VÀ KẾ HOẠCH NÂNG CẤP THEO GÓP Ý CỦA BOSS
**Dự án:** Camera DNC AI (V2)  
**Ngày lập:** 17/11/2026  
**Mục đích:** Đối chiếu hiện trạng mã nguồn, giải trình các vấn đề kỹ thuật và cung cấp kế hoạch triển khai chi tiết cho các góp ý của Ban Giám hiệu / Boss.

---

## MỤC LỤC
1. [Góp ý 1: Lưu video "Nhãn Đỏ" lâu hơn 1 tháng (> 30 ngày)](#1-góp-ý-1-lưu-video-nhãn-đỏ-lâu-hơn-1-tháng--30-ngày)
2. [Góp ý 2: Bắn thông báo Đỏ ra kênh ngoài (Zalo, Gmail, Telegram)](#2-góp-ý-2-bắn-thông-báo-đỏ-ra-kênh-ngoài-zalo-gmail-telegram)
3. [Kiểm tra 3: Khả năng đọc và trả lời Báo cáo Đêm của AI Agent](#3-kiểm-tra-3-khả-năng-đọc-và-trả-lời-báo-cáo-đêm-của-ai-agent)
4. [Kiểm tra 4: Điều tra nguyên nhân lỗi "Không phân tích được âm thanh"](#4-kiểm-tra-4-điều-tra-nguyên-nhân-lỗi-không-phân-tích-được-âm-thanh)
5. [Lộ trình hành động chi tiết (Action Plan)](#5-lộ-trình-hành-động-chi-tiết-action-plan)

---

## 1. Góp ý 1: Lưu video "Nhãn Đỏ" lâu hơn 1 tháng (> 30 ngày)

### 1.1. Hiện trạng trong mã nguồn
- Tham số vòng đời hiện tại được cố định là 30 ngày: `CAMERAAI_RETENTION_DAYS=30` (tại `CameraAI/config.py` dòng 238).
- Luồng dọn dẹp nền `metadata_cleanup_loop` (tại `CameraAI/main.py` dòng 741) chạy định kỳ mỗi 6 giờ và gọi hàm `purge_expired_metadata()` (dòng 650):
  1. **Trên Synology FileStation:** Quét các thư mục `cameras/{cam}/{year}/{month}/{day}`. Nếu ngày lịch < ngày ngưỡng (30 ngày trước), hệ thống gọi lệnh xóa **toàn bộ thư mục ngày** (`purge_expired_day_folders` tại `CameraAI/synology_storage.py` dòng 372).
  2. **Trong bộ nhớ đệm máy chủ:** Xóa toàn bộ thư mục ngày tương ứng tại `storage/clips/cameras/{cam}/{Y}/{M}/{D}`.
  3. **Trong CSDL SQLite & Postgres:** Chạy lệnh `DELETE FROM events WHERE timestamp < ?` (`delete_expired_events` tại `CameraAI/database.py` dòng 522).
- **Vấn đề cốt lõi:** Khi xóa cả thư mục ngày theo lịch cuốn chiếu 30 ngày, **tất cả các video clip bằng chứng nhãn đỏ (`severity == 'high'`) cũng bị xóa sạch**, không giữ lại được.

### 1.2. Giải pháp kỹ thuật triển khai

```
                     ┌── Video Thường (severity = 'info' / 'medium') ──► Giữ 30 ngày (xóa theo ngày)
                     │
Sự kiện camera ──────┤
                     │
                     └── Video Nhãn Đỏ (severity = 'high' / Anomaly)  ──► Lưu vùng an toàn (Archive)
                                                                          Giữ 90 - 180 ngày hoặc vĩnh viễn
```

#### Các bước triển khai:
1. **Phân loại lưu trữ (Storage Tiering):**
   - Khi `clip_capture_worker.py` cắt video cảnh báo đỏ (`severity == 'high'` hoặc thuộc nhóm nguy cơ như `Intrusion`, `Fight`, `CrossLine`):
     - Ghi thêm một bản sao hoặc chuyển hướng lưu vào thư mục an toàn: `cameras_protected/{cam}/{year}/{month}/{day}/{clip_filename}` (trên Synology NAS lẫn local).
2. **Cập nhật CSDL:**
   - Thêm cờ `is_protected INTEGER DEFAULT 0` trong bảng `events`. Các sự kiện nhãn đỏ sẽ được đánh dấu `is_protected = 1`.
3. **Cập nhật quy tắc dọn dẹp (`purge_expired_metadata`):**
   - Khi xóa CSDL: `DELETE FROM events WHERE timestamp < cutoff AND is_protected = 0`.
   - Đối với các sự kiện có `is_protected = 1`: Áp dụng `cutoff_protected` riêng biệt (ví dụ: 90 ngày hoặc 180 ngày).
   - Khi xóa thư mục trên Synology / Local: Chỉ xóa thư mục ngày nếu bên trong không còn file nào thuộc diện được bảo vệ (`is_protected`).

---

## 2. Góp ý 2: Bắn thông báo Đỏ ra kênh ngoài (Zalo, Gmail, Telegram)

### 2.1. Hiện trạng
- Hệ thống mới chỉ phát sóng cảnh báo cục bộ qua giao thức **WebSocket** (`broadcast_event_sync` trong `CameraAI/main.py` dòng 545).
- Người dùng chỉ nhận được chuông/thông báo khi đang mở trình duyệt web.

### 2.2. Đánh giá tính khả thi và độ phức tạp các kênh

| Kênh tích hợp | Đánh giá độ khó | Tốc độ gửi tin | Chi phí / Giới hạn API | Đề xuất |
| :--- | :---: | :---: | :---: | :--- |
| **Telegram Group Bot** | **Rất dễ (1 - 2 giờ)** | Tức thì (< 1 giây) | **Hoàn toàn miễn phí**, không bị bóp băng thông, gửi kèm ảnh snapshot và video clip trực tiếp | **Nên bật ngay làm kênh phản ứng nhanh** |
| **Gmail (Email SMTP)** | **Dễ (2 - 3 giờ)** | 3 - 5 giây | Miễn phí (dùng Gmail App Password của Google Workspace trường) | **Rất tốt để gửi báo cáo văn bản lưu vết** |
| **Group Zalo** | **Trung bình - Khó** | 2 - 4 giây | Zalo không hỗ trợ mở Webhook nhóm tự do như Telegram; cần dùng Bot Bridge hoặc Zalo OA có phí | **Triển khai theo lộ trình bên dưới** |

### 2.3. Hướng giải quyết cho Group Zalo
Để thông báo vào nhóm Zalo của Ban Giám hiệu / Đội An ninh:
1. **Phương án Zalo Bot Bridge (Tối ưu nhất cho Group nội bộ):**
   - Dùng một dịch vụ Zalo Chatbot Bridge (Node.js/Python chạy ngầm đăng nhập tài khoản Zalo thông báo hoặc qua giao thức Webhook của Chatwork/Lark/Zalo Web).
   - Khi có sự kiện đỏ, backend gọi webhook nội bộ: `POST http://localhost:PORT/send-zalo` kèm nội dung và link snapshot.
2. **Phương án Zalo OA (Zalo Official Account Doanh nghiệp):**
   - Sử dụng Zalo ZNS (Zalo Notification Service) gửi tin nhắn thông báo đến danh sách số điện thoại của lãnh đạo/bảo vệ. Phương án này yêu cầu xác thực doanh nghiệp và mẫu tin duyệt trước.
3. **Đề xuất thực hiện:**
   - **Bước 1 (Làm ngay):** Bật **Telegram Group** và **Gmail** trước để bảo đảm không bị sót cảnh báo đỏ.
   - **Bước 2:** Kết nối Zalo Group thông qua module Zalo Webhook Bridge.

---

## 3. Kiểm tra 3: Khả năng đọc và trả lời Báo cáo Đêm của AI Agent

### 3.1. Kết luận kiểm tra mã nguồn: **AI ĐÃ HOÀN TOÀN CÓ TÍNH NĂNG NÀY**
Mã nguồn tại `CameraAI/main.py` (dòng 1885 - 1948) và `CameraAI/nightly_report_worker.py` (dòng 925 - 1050) đã được xây dựng sẵn kiến trúc **RAG Grounding** chuyên sâu cho Báo cáo Đêm.

### 3.2. Quy trình AI truy xuất Báo cáo Đêm khi người dùng Chat
1. **Phát hiện ý định truy vấn (Intent Planning):**
   Khi người dùng gửi câu hỏi, hệ thống kiểm tra các từ khóa báo cáo trong `ai_search_planner.py`:
   - Danh sách từ khóa: `báo cáo`, `bao cao`, `ca trực`, `ca truc`, `đêm qua`, `dem qua`, `tối qua`, `toi qua`, `tổng kết`, `tong ket`, `an ninh`, `ca đêm`, `ca dem`, `trực đêm`, `truc dem`, `diễn biến ca`.
2. **Nạp dữ liệu từ cấu trúc Báo cáo Đêm:**
   Hàm `get_nightly_report_for_ai()` tự động tìm file báo cáo đêm của ngày yêu cầu (hoặc ngày gần nhất có báo cáo):
   - Nếu hỏi toàn trường: Đọc `storage/nightly_reports/YYYY-MM-DD/_daily_master_summary.json`.
   - Nếu hỏi riêng một camera: Đọc `storage/nightly_reports/YYYY-MM-DD/cam_XX.json`.
   - Nếu máy cục bộ chưa có file: Tự động tải từ Synology NAS (`synology_storage.download_nightly_report_file`).
3. **Cung cấp ngữ cảnh cho mô hình AI (RAG Grounding):**
   Dữ liệu được nạp vào Prompt cho mô hình ngôn ngữ lớn (GLM-5.3-Flash / Qwen) gồm:
   - Đánh giá mức độ rủi ro (Bình thường / Cảnh báo / Nghiêm trọng).
   - Thống kê toàn ca: Tổng số sự kiện, số bất thường, số người, số xe, số video clip.
   - Diễn biến chi tiết theo 4 ca trực nối tiếp (từ 22h hôm trước đến 22h hôm sau).
   - Danh sách các sự kiện bất thường nổi bật kèm mã `#ID` để người dùng bấm xem video trực tiếp.

### 3.3. Các điều kiện cần tuân thủ để AI trả lời đúng từ Báo cáo Đêm
- **Điều kiện 1: File Báo cáo đêm phải đã được khởi tạo.**
  Báo cáo được tạo bởi tiến trình chạy ngầm `nightly_report_worker` (tự động chạy sau 22h và 04h sáng hàng ngày). Nếu ngày đó chưa từng sinh báo cáo và NAS không có file, AI sẽ fallback về tìm kiếm thô trong CSDL sự kiện.
- **Điều kiện 2: Từ khóa trong câu hỏi.**
  Người dùng nên hỏi câu có chứa các từ khóa nêu trên hoặc nêu ngày cụ thể (Ví dụ: *"Báo cáo đêm qua tình hình an ninh thế nào?"*, *"Tóm tắt ca trực đêm ngày 15/11/2026"*).
- **Điều kiện 3: Phân quyền tài khoản (RBAC):**
  Tài khoản đăng nhập chỉ xem được thông tin của các camera mà tài khoản đó được cấp quyền quản lý.

---

## 4. Kiểm tra 4: Điều tra nguyên nhân lỗi "Không phân tích được âm thanh"

Khi tra cứu video trong giao diện Tìm kiếm thông minh, hệ thống liên tục báo không phân tích được âm thanh. Kết quả kiểm tra chi tiết mã nguồn đã xác định được **3 nguyên nhân gốc rễ liên hoàn**:

```
[ Clip MP4 ]
      │
      ▼
1. ffprobe kiểm tra audio stream ──► BỊ LỖI: Windows không có lệnh ffprobe trong PATH
      │                              (Bị bắt lỗi trong try/except -> Gán has_audio_track = False)
      ▼
2. Kết quả ────────────────────────► Giao diện luôn báo: "Video không có track âm thanh"
      │
      ▼ (Nếu cưỡng bức vượt qua bước 1)
3. Gửi lên Server AI nội bộ ───────► BỊ LỖI: https://.../v1/audio/analyze trả về HTTP 404 (Không tồn tại)
      │
      ▼
4. Fallback Gemini Audio ──────────► BỊ LỖI: Chưa cấu hình GEMINI_API_KEY (configured: False)
      │
      ▼
5. Fallback Faster-Whisper local ──► BỊ LỖI: Thiếu thư viện (ModuleNotFoundError: 'faster_whisper')
      │
      ▼
[ HẬU QUẢ CUỐI CÙNG ] ────────────► "Không thể phân tích nội dung âm thanh"
```

### 4.1. Chi tiết các nguyên nhân:
1. **Lệnh `ffprobe` không khả dụng:**
   - Tại `CameraAI/internal_audio_client.py` dòng 177: Gọi `subprocess.run([config.FFPROBE_PATH, ...])`.
   - `config.FFPROBE_PATH` mặc định là chuỗi `"ffprobe"`. Trên Windows máy trạm, thư viện `imageio_ffmpeg` chỉ cung cấp `ffmpeg.exe` chứ không có `ffprobe.exe`.
   - Kết quả: Lệnh ném ngoại lệ `FileNotFoundError`, biến `has_audio_track` bị gán cứng thành `False`.
2. **Server AI nội bộ chưa mở Endpoint Audio:**
   - Trong file `.env`: `INTERNAL_AUDIO_SERVER_URL=https://llm.ttpmsandbox.us.kg/v1/audio`.
   - Endpoint `/analyze` và `/transcribe` trên domain này trả về HTTP 404. Server này hiện chỉ cấu hình các mô hình Text/Vision (`GLM-5.3-Flash`, `Qwen3.8-Flash-Next`, `DeepSeek-V4.1-Flash`), chưa deploy cụm mô hình Whisper STT.
3. **Các tầng bảo hiểm Fallback đều bị hỏng:**
   - Fallback Gemini: Chưa điền API Key.
   - Fallback Local Faster-Whisper: Chưa cài đặt thư viện vào Python 3.12 của hệ thống.

---

## 5. Lộ trình hành động chi tiết (Action Plan)

### Giai đoạn 1: Khắc phục sự cố Âm thanh (Ưu tiên số 1 - 0.5 ngày)
- [ ] **Sửa code trích xuất âm thanh:** Thay vì phụ thuộc vào `ffprobe`, chuyển sang dùng trực tiếp file `ffmpeg.exe` (đã có đường dẫn tuyệt đối chuẩn trong `config.FFMPEG_PATH`) để kiểm tra và trích xuất luồng WAV 16kHz.
- [ ] **Cài đặt thư viện Fallback âm thanh cục bộ:** Cài `faster-whisper` cho môi trường Python trên máy trạm để máy tự động nghe và bóc băng tiếng Việt trực tiếp khi Server AI vắng mặt:
  ```bash
  pip install faster-whisper
  ```
- [ ] **Bổ sung GEMINI_API_KEY:** Cấu hình key dự phòng để kích hoạt khả năng nghe hiểu đa phương thức của Gemini.

### Giai đoạn 2: Bắn thông báo Đỏ ra kênh ngoài (Ưu tiên số 2 - 1 ngày)
- [ ] **Tạo Module Thông báo Đa kênh (`alert_dispatcher.py`):**
  - Khi `broadcast_event_sync` nhận sự kiện có `severity == 'high'`:
    - Gửi tin tức thì qua **Telegram Group Bot** (kèm ảnh snapshot hiện trường và nút mở link xem clip).
    - Gửi email cảnh báo qua **Gmail SMTP** đến danh sách `GOOGLE_ADMIN_EMAILS`.
- [ ] **Tích hợp Webhook Group Zalo:**
  - Thiết lập endpoint chuyển tiếp tin nhắn vào Group Zalo của đội an ninh trường.

### Giai đoạn 3: Điều chỉnh Retention lưu trữ Video Nhãn Đỏ > 30 ngày (Ưu tiên số 3 - 1 ngày)
- [ ] Bổ sung trường `is_protected` vào bảng `events` trong CSDL SQLite và Postgres.
- [ ] Khi phát hiện sự kiện nhãn đỏ, tạo thêm liên kết hoặc sao lưu clip vào thư mục bảo vệ `cameras_protected/`.
- [ ] Sửa hàm `purge_expired_day_folders` và `delete_expired_events`: Bỏ qua các ngày/clip được đánh dấu bảo vệ, áp dụng thời gian lưu trữ dài hạn (90 - 180 ngày).

---
*Tài liệu này được lưu tại thư mục dự án `docs/BAO_CAO_GOP_Y_BOSS_VA_PHAN_TICH_HE_THONG.md` để theo dõi và đối chiếu tiến độ triển khai.*
