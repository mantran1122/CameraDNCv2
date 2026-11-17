# HƯỚNG DẪN KẾT NỐI BOT BẮN CẢNH BÁO ĐỎ VÀO ZALO GROUP

Dịch vụ này giúp tự động chuyển tiếp các sự kiện cảnh báo đỏ nguy cấp (**Ẩu đả, Đột nhập, Âm thanh bất thường**) từ hệ thống Camera AI DNC vào trực tiếp Nhóm Zalo an ninh:
👉 **Link nhóm Zalo:** [https://zalo.me/g/libazgippahcfbk99qkc](https://zalo.me/g/libazgippahcfbk99qkc)

---

## 🚀 3 BƯỚC KÍCH HOẠT NHANH (MẤT 1 PHÚT)

### Bước 1: Khởi động Bot Zalo Bridge trên máy chủ
Trên terminal máy chủ (hoặc máy trạm):
```bash
cd ~/projects/CameraDNCv2/scripts/zalo_bridge
npm install
npm start
```
Terminal sẽ in ra một **mã QR**.

### Bước 2: Quét mã QR trên điện thoại
1. Mở ứng dụng Zalo trên điện thoại (dùng nick phụ hoặc nick của bạn).
2. Quét mã QR trên màn hình terminal để đăng nhập bot.
3. Bot sẽ lưu phiên vào file `appstate.json` (từ lần sau sẽ tự động đăng nhập, không cần quét lại).

### Bước 3: Kích hoạt nhóm nhận tin
1. Đảm bảo tài khoản Zalo vừa quét QR đã tham gia nhóm: **https://zalo.me/g/libazgippahcfbk99qkc**
2. Vào nhóm chat đó và gõ lệnh:
   ```text
   /setalert
   ```
3. Bot sẽ tự động trả lời xác nhận:
   > *"✅ ĐÃ LIÊN KẾT NHÓM THÀNH CÔNG! Kể từ bây giờ, mọi cảnh báo đỏ từ hệ thống Camera AI DNC sẽ tự động được gửi vào nhóm này."*

---

## ⚙️ Cấu hình Camera AI nhận Webhook
Trong file `CameraAI/.env` trên máy chủ, thiết lập:
```bash
ZALO_WEBHOOK_URL=http://127.0.0.1:5055/webhook
```
*(Hoặc vào trang Web Admin `http://<IP_MAY_CHU>:8000/admin` -> Tab 4 -> Điền URL và bấm **"Bắn Tin Test vào Zalo"**)*.
