# KẾ HOẠCH 6: LƯU TRỮ VIDEO ĐỎ TRÊN 1 THÁNG, THÔNG BÁO GROUP ZALO/GMAIL VÀ KHẮC PHỤC LỖI ÂM THANH

> **Tài liệu tham chiếu:** [BAO_CAO_GOP_Y_BOSS_VA_PHAN_TICH_HE_THONG.md](../BAO_CAO_GOP_Y_BOSS_VA_PHAN_TICH_HE_THONG.md)  
> **Thời gian tạo:** 17/11/2026  
> **Trạng thái:** Sẵn sàng triển khai  

---

## 1. TÓM TẮT CÁC YÊU CẦU MỚI TỪ BOSS
1. **Lưu video nhãn đỏ > 1 tháng:** Không để cơ chế dọn dẹp cuốn chiếu 30 ngày xóa mất video bằng chứng của các cảnh báo đỏ / nguy cấp.
2. **Bắn thông báo đỏ ra ngoài app:** Ngoài chuông và popup trong web app, cần bắn thông báo ra Group Zalo, Gmail hoặc Telegram.
3. **Kiểm tra AI đọc Báo cáo Đêm:** Đánh giá khả năng AI truy xuất Báo cáo Đêm khi người dùng chat hỏi, điều kiện kích hoạt.
4. **Khắc phục lỗi Phân tích Âm thanh:** Tìm nguyên nhân tại sao video nào tra ra cũng "không phân tích được âm thanh" và sửa dứt điểm.

---

## 2. HIỆN TRẠNG KỸ THUẬT & NGUYÊN NHÂN GỐC RỄ

### 2.1. Về Retention Video Đỏ
- **Code hiện tại:** `purge_expired_metadata()` (`main.py` dòng 650) và `purge_expired_day_folders()` (`synology_storage.py` dòng 372) xóa nguyên folder ngày `cameras/{cam}/{Y}/{M}/{D}` nếu ngày đó > 30 ngày.
- **Hệ quả:** Mọi clip nhãn đỏ nằm trong ngày bị xóa đều mất theo.
- **Khắc phục:** Thêm trường `is_protected` trong DB, sao lưu/chuyển các clip đỏ sang vùng an toàn `cameras_protected/`, giữ 90 - 180 ngày.

### 2.2. Về Kênh thông báo ngoài
- **Code hiện tại:** Chỉ có WebSocket nội bộ (`manager.broadcast()` trong `main.py`).
- **Khắc phục:** Viết module `alert_dispatcher.py` để khi có sự kiện `severity == 'high'`:
  - Bắn tin khẩn qua **Telegram Group Bot** (nhanh nhất, miễn phí, đính kèm ảnh chụp snapshot).
  - Gửi **Gmail** cho Ban Giám hiệu.
  - Chuyển tiếp vào **Group Zalo** qua Zalo Webhook Bridge.

### 2.3. Về AI đọc Báo cáo Đêm
- **Hiện trạng:** Code **đã hoàn thành** cơ chế RAG tại `main.py` (dòng 1885 - 1948) và `nightly_report_worker.py` (dòng 925 - 1050).
- **Điều kiện kích hoạt:**
  - File báo cáo ngày đó đã được sinh ra trong `storage/nightly_reports/YYYY-MM-DD/`.
  - Câu hỏi chứa từ khóa: `báo cáo`, `ca trực`, `đêm qua`, `tình hình đêm`, `an ninh`, `tổng kết`...
  - Tài khoản có quyền RBAC với camera tương ứng.

### 2.4. Về Lỗi Phân tích Âm thanh
- **Nguyên nhân 1:** Lệnh `ffprobe` không có trong PATH trên Windows (`imageio_ffmpeg` chỉ cấp `ffmpeg.exe`), làm ném `FileNotFoundError` và luôn đánh giá clip là `no_audio_track`.
- **Nguyên nhân 2:** Server AI nội bộ tại URL `https://llm.ttpmsandbox.us.kg/v1/audio/analyze` trả về HTTP 404 (chưa mở endpoint Audio STT).
- **Nguyên nhân 3:** Thư viện fallback `faster_whisper` chưa được cài đặt trong môi trường Python 3.12 của máy.

---

## 3. CHECKLIST CÔNG VIỆC TRIỂN KHAI

- [ ] **Sửa lỗi âm thanh (0.5 ngày):**
  - [ ] Đổi logic kiểm tra audio stream trong `internal_audio_client.py` sang dùng trực tiếp file `ffmpeg.exe` có sẵn.
  - [ ] Chạy lệnh `pip install faster-whisper` trên máy trạm để kích hoạt fallback STT tiếng Việt cục bộ.
- [ ] **Thông báo đỏ đa kênh (1 ngày):**
  - [ ] Tạo module `alert_dispatcher.py` lắng nghe sự kiện `severity == 'high'`.
  - [ ] Tích hợp bot Telegram gửi ảnh snapshot vào nhóm bảo vệ/lãnh đạo.
  - [ ] Tích hợp gửi email Gmail.
  - [ ] Kết nối Webhook Group Zalo.
- [ ] **Chính sách Retention video đỏ (1 ngày):**
  - [ ] Thêm cờ `is_protected` vào CSDL `events`.
  - [ ] Tách thư mục lưu trữ `cameras_protected/` trên NAS Synology.
  - [ ] Sửa hàm dọn dẹp calendar để không xóa video đỏ trong vòng 90 - 180 ngày.
