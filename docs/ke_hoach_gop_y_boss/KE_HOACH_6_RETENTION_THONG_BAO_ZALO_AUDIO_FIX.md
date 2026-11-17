# KẾ HOẠCH 6: LƯU TRỮ VIDEO ĐỎ TRÊN 1 THÁNG, THÔNG BÁO GROUP ZALO/GMAIL VÀ KHẮC PHỤC LỖI ÂM THANH

> **Tài liệu tham chiếu:** [BAO_CAO_GOP_Y_BOSS_VA_PHAN_TICH_HE_THONG.md](../BAO_CAO_GOP_Y_BOSS_VA_PHAN_TICH_HE_THONG.md)  
> **Thời gian tạo:** 17/11/2026  
> **Trạng thái:** Đã hoàn thành 100% & Sẵn sàng đưa lên Production  

---

## 1. TÓM TẮT CÁC YÊU CẦU MỚI TỪ BOSS
1. **Lưu video nhãn đỏ > 1 tháng:** Không để cơ chế dọn dẹp cuốn chiếu 30 ngày xóa mất video bằng chứng của các cảnh báo đỏ / nguy cấp.
2. **Bắn thông báo đỏ ra ngoài app:** Ngoài chuông và popup trong web app, cần bắn thông báo ra Group Zalo, Gmail hoặc Telegram.
3. **Kiểm tra AI đọc Báo cáo Đêm:** Đánh giá khả năng AI truy xuất Báo cáo Đêm khi người dùng chat hỏi, điều kiện kích hoạt.
4. **Khắc phục lỗi Phân tích Âm thanh:** Tìm nguyên nhân tại sao video nào tra ra cũng "không phân tích được âm thanh" và sửa dứt điểm.
5. **Tối ưu hóa Lọc & Phân trang đa trang Google/YouTube cho 17,500+ sự kiện Đỏ:** Tách rời thao tác click pill khỏi tự động tìm kiếm ngay lập tức; liên kết đa điều kiện (Mức độ rủi ro, Camera, Ngày/Giờ, Số clip / trang); chỉ thực thi khi bấm [Áp dụng]; phân trang chuẩn tránh treo mạng.

---

## 2. HIỆN TRẠNG KỸ THUẬT & NGUYÊN NHÂN GỐC RỄ

### 2.1. Về Retention Video Đỏ
- **Code trước đó:** `purge_expired_metadata()` (`main.py`) và `purge_expired_day_folders()` (`synology_storage.py`) xóa nguyên folder ngày `cameras/{cam}/{Y}/{M}/{D}` nếu ngày đó > 30 ngày.
- **Hệ quả:** Mọi clip nhãn đỏ nằm trong ngày bị xóa đều mất theo.
- **Đã khắc phục:**
  - Thêm trường `is_protected INTEGER DEFAULT 0` vào bảng `events` (tự động bật `1` khi `severity == 'high'`).
  - Hàm `get_protected_clip_filenames()` và `delete_expired_events()` bảo vệ clip đỏ tối thiểu 90 ngày.
  - Sửa hàm dọn dẹp ngày cũ: kiểm tra nếu folder có clip được bảo vệ thì chỉ xóa các clip thường, giữ nguyên clip đỏ và folder.

### 2.2. Về Kênh thông báo ngoài
- **Code trước đó:** Chỉ có WebSocket nội bộ (`manager.broadcast()` trong `main.py`).
- **Đã khắc phục:**
  - Viết module `alert_dispatcher.py` với hàng đợi nền bất đồng bộ, bộ đệm cooldown debounce 20s chống spam.
  - Tích hợp bot **Telegram** gửi tin nhắn khẩn kèm ảnh chụp snapshot.
  - Tích hợp gửi **Gmail SMTP** (SSL/TLS).
  - Tích hợp Webhook **Zalo** (gửi tin nhắn vào Group Zalo quản lý).
  - Tích hợp trực tiếp vào hàm `broadcast_event_sync` tại `CameraAI/main.py`.

### 2.3. Về AI đọc Báo cáo Đêm
- **Hiện trạng:** Code **đã hoàn thành** cơ chế RAG tại `main.py` và `nightly_report_worker.py`.
- **Điều kiện kích hoạt:**
  - File báo cáo ngày đó đã được sinh ra trong `storage/nightly_reports/YYYY-MM-DD/`.
  - Câu hỏi chứa từ khóa: `báo cáo`, `ca trực`, `đêm qua`, `tình hình đêm`, `an ninh`, `tổng kết`...
  - Tài khoản có quyền RBAC với camera tương ứng.

### 2.4. Về Lỗi Phân tích Âm thanh
- **Nguyên nhân:** Lệnh `ffprobe` không có trong PATH trên Windows (`imageio_ffmpeg` chỉ cấp `ffmpeg.exe`), làm ném `FileNotFoundError` và luôn đánh giá clip là `no_audio_track`.
- **Đã khắc phục:**
  - Viết lại hàm `_check_audio_track()` dùng trực tiếp `ffmpeg -i <file>` kiểm tra luồng Audio từ `stderr`.
  - Bổ sung fallback endpoint chuẩn OpenAI `/v1/audio/transcriptions`.
  - Đo và báo cáo mức âm lượng dBFS thực tế nếu môi trường không có lời nói.

---

## 3. CHECKLIST CÔNG VIỆC TRIỂN KHAI

- [x] **Sửa lỗi âm thanh:**
  - [x] Đổi logic kiểm tra audio stream trong `internal_audio_client.py` và `audio_analysis_worker.py` sang dùng trực tiếp `ffmpeg.exe` có sẵn.
  - [x] Tích hợp fallback endpoint OpenAI `/v1/audio/transcriptions` và đo âm lượng RMS dBFS chi tiết.
- [x] **Thông báo đỏ đa kênh:**
  - [x] Tạo module `alert_dispatcher.py` lắng nghe sự kiện `severity == 'high'`.
  - [x] Tích hợp bot Telegram gửi cảnh báo khẩn và ảnh snapshot vào nhóm bảo vệ/lãnh đạo.
  - [x] Tích hợp gửi email Gmail qua giao thức SMTP bảo mật.
  - [x] Kết nối Webhook Group Zalo.
  - [x] Móc nối tự động vào hàm phát sự kiện realtime `broadcast_event_sync` trong `main.py`.
  - [x] **Ma trận Cấu hình Thông báo Zalo trong Admin Control Center:** Cho phép Admin tự chọn loại hành vi gửi (nút 1-click 'Chỉ chọn Cảnh báo Đỏ', loại bỏ 'Phát hiện người' / 'Chuyển động') và chọn danh sách Camera các phòng theo dõi. Lưu cấu hình bền vững vào `storage/alert_config.json`.
- [x] **Chính sách Retention video đỏ:**
  - [x] Thêm cờ `is_protected` vào CSDL `events` trong `database.py` (tự động bật khi `severity == 'high'`).
  - [x] Cập nhật hàm dọn dẹp `delete_expired_events()` giữ video đỏ 90 ngày.
  - [x] Sửa `purge_expired_day_folders()` trong `synology_storage.py` và `purge_expired_metadata()` trong `main.py` để giữ lại các clip đỏ và folder chứa chúng.
- [x] **Tối ưu hóa Bộ Lọc & Phân trang Đa trang kiểu Google/YouTube (Xử lý 17,500+ sự kiện đỏ):**
  - [x] **Tách rời click pill khỏi tự động tìm kiếm:** Bấm các pill Mức độ rủi ro, Camera, Thời gian chỉ đổi màu và lưu bộ nhớ, không tự ý search hay đóng modal.
  - [x] **Liên kết toàn diện đa điều kiện:** Gom đủ Mức độ (Đỏ/Vàng/Thông thường) + Camera (Tất cả / Kênh cụ thể) + Thời gian (Hôm nay / Khoảng ngày Từ... Đến...) + Số clip/trang (`[12] [24] [48] [100] [Tất cả]`).
  - [x] **Thực thi duy nhất khi bấm `[Áp dụng]`:** Gửi 1 request duy nhất về backend, đóng popup và hiển thị kết quả.
  - [x] **Nút `[Đặt lại]`:** Khôi phục toàn bộ bộ lọc về mặc định.
  - [x] **Phân trang đa trang Google/YouTube:** Chỉ load theo kích thước trang (`page_size`), hỗ trợ chuyển trang 1, 2, 3... mượt mà, chống sập mạng và treo giao diện.
  - [x] **Khắc phục backend `vss_search_engine.py`:** Loại bỏ hoàn toàn fallback chèn clip rác khi tìm kiếm sự kiện đỏ.
