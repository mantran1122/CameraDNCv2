# HƯỚNG DẪN KẾT NỐI BẮN CẢNH BÁO ĐỎ VÀO ZALO GROUP

Module này cung cấp dịch vụ **Zalo Group Webhook Bridge** để nhận cảnh báo nguy cấp (Nhãn Đỏ) từ hệ thống Camera AI DNC và chuyển tiếp tức thì vào Group Zalo của Ban Giám hiệu / Đội Bảo vệ.

---

## 1. Cơ chế hoạt động

```
[Camera AI DNC] 
      │ (Phát hiện ẩu đả / đột nhập / âm thanh la hét)
      ▼
[alert_dispatcher.py] 
      │ (Tự động gửi HTTP POST Webhook JSON)
      ▼
[Zalo Group Webhook Bridge] (URL: http://127.0.0.1:5000/webhook)
      │
      ▼
[Group Zalo Ban Giám Hiệu / An Ninh] (Nhận tin nhắn báo động + link clip)
```

---

## 2. Cách thiết lập cấu hình

### Cách A: Cấu hình trực tiếp trên Web Admin (Dễ nhất)
1. Mở trang quản trị: `http://<IP_MAY_CHU>:8000/admin`
2. Đăng nhập bằng tài khoản Quản trị viên.
3. Chọn Tab **4. Cấu hình AI & Prompt** -> Tìm mục **"Bắn Cảnh Báo Đỏ vào Zalo Group"**.
4. Điền **Zalo Webhook URL** (Ví dụ: `http://127.0.0.1:5000/webhook` hoặc URL webhook bot Zalo của trường).
5. Bấm nút **"Bắn Tin Test vào Zalo"** để kiểm tra ngay lập tức.
6. Bấm **"Lưu Cấu Hình Zalo"**.

### Cách B: Cấu hình qua file `.env` trên máy chủ
Mở file `~/projects/CameraDNCv2/CameraAI/.env` và thêm:
```bash
ZALO_WEBHOOK_URL=http://127.0.0.1:5000/webhook
ZALO_WEBHOOK_SECRET=your_secret_token_here
```

---

## 3. Khởi chạy Bridge độc lập (Tùy chọn)

Nếu bạn chưa có sẵn Webhook Zalo và muốn chạy một bridge microservice nội bộ:

```bash
cd ~/projects/CameraDNCv2/scripts/zalo_bridge
python bridge.py
```
Bridge sẽ lắng nghe tại `http://0.0.0.0:5000/webhook`.
Mỗi khi có sự kiện đỏ, bridge sẽ in ra console và chuyển tiếp tới Zalo Group ID được cấu hình.
