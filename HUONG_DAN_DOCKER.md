# HƯỚNG DẪN ĐÓNG GÓI & CHẠY CAMERAAI BẰNG DOCKER

Hệ thống **CameraAI (Dahua NVR AI Summarizer & Search Studio)** đã được đóng gói hoàn chỉnh bằng Docker.

---

## 1. Cấu trúc đóng gói Docker

* [`CameraAI/Dockerfile`](file:///d:/CameraV2/CameraAI/Dockerfile): Đóng gói Python 3.11, FFmpeg/FFprobe, OpenCV Headless, múi giờ Việt Nam (`Asia/Ho_Chi_Minh`) và toàn bộ thư viện cần thiết.
* [`CameraAI/.dockerignore`](file:///d:/CameraV2/CameraAI/.dockerignore): Loại trừ file tạm, cache, clip video cũ khi build image giúp image nhẹ và build nhanh.
* [`docker-compose.yml`](file:///d:/CameraV2/docker-compose.yml): Cấu hình chạy container, mở cổng `8000:8000`, tự động khởi động lại khi gặp sự cố (`restart: unless-stopped`).
* **Volume Mount (`./CameraAI/storage:/app/storage`)**: Toàn bộ cơ sở dữ liệu SQLite (`camera_metadata.db`), video clip cảnh báo (`storage/clips`) và cấu hình NVR (`nvr_config.json`) được lưu trực tiếp trên ổ cứng máy chủ, không bị mất khi tắt/cập nhật container.

---

## 2. Cách khởi chạy trên Linux

### Bước 1: Cài đặt Docker (nếu máy Linux chưa có)
Trên Ubuntu / Debian:
```bash
sudo apt update
sudo apt install -y docker.io docker-compose-plugin
sudo usermod -aG docker $USER
```
*(Đăng xuất rồi đăng nhập lại để cập nhật quyền chạy Docker không cần sudo).*

### Bước 2: Chạy hệ thống
Tại thư mục dự án `CameraDNCv2`, chạy lệnh:
```bash
docker compose up -d --build
```
Hoặc dùng file script đã tạo sẵn:
```bash
chmod +x run_docker.sh
./run_docker.sh
```

---

## 3. Cách khởi chạy trên Windows (nếu có Docker Desktop)

Chỉ cần nhấp đúp chuột vào file:
* [`run_docker.bat`](file:///d:/CameraV2/run_docker.bat)

---

## 4. Truy cập giao diện & Sử dụng

* **Giao diện Search & Dashboard**: Mở trình duyệt vào địa chỉ:
  `http://localhost:8000/search` hoặc `http://<IP_MAY_LINUX>:8000/search`
* **Trang chủ API**:
  `http://localhost:8000/`
* **Tài liệu API Swagger**:
  `http://localhost:8000/docs`

---

## 5. Các lệnh quản trị thường dùng

* **Xem log hoạt động thời gian thực**:
  ```bash
  docker compose logs -f
  ```
* **Khởi động lại hệ thống**:
  ```bash
  docker compose restart
  ```
* **Dừng hệ thống**:
  ```bash
  docker compose down
  ```
* **Cập nhật code mới sau này**:
  ```bash
  git pull
  docker compose up -d --build
  ```

