# HƯỚNG DẪN ĐÓNG GÓI & CHẠY CAMERAAI BẰNG DOCKER

Hệ thống **CameraAI (Dahua NVR AI Summarizer & Search Studio)** được đóng gói hoàn chỉnh bằng Docker với đầy đủ **PostgreSQL tập trung** và cơ chế **lưu trữ video clip trực tiếp lên NAS**.

---

## 1. Cấu trúc đóng gói Docker

* [`CameraAI/Dockerfile`](file:///d:/CameraV2/CameraAI/Dockerfile): Đóng gói Python 3.11, FFmpeg/FFprobe, OpenCV Headless, múi giờ Việt Nam (`Asia/Ho_Chi_Minh`) và toàn bộ thư viện cần thiết.
* [`CameraAI/.dockerignore`](file:///d:/CameraV2/CameraAI/.dockerignore): Loại trừ file tạm, cache, clip video cũ khi build image giúp image nhẹ và build nhanh.
* [`docker-compose.yml`](file:///d:/CameraV2/docker-compose.yml): 
  - **`camera-postgres` (PostgreSQL 16)**: Cung cấp cơ sở dữ liệu quan hệ mạnh mẽ, tự động nạp bảng từ `postgres_schema.sql`, mở cổng `5432:5432`.
  - **`camera-ai-service`**: Chạy backend FastAPI, tự động kết nối NVR Dahua, tự động đồng bộ Dual-Write từ SQLite sang PostgreSQL qua Outbox Pattern.
* **Volume Mount**:
  - `./CameraAI/storage:/app/storage`: Lưu cấu hình NVR (`nvr_config.json`), database SQLite cục bộ.
  - Hỗ trợ mount trực tiếp thư mục NAS vào `/app/storage/clips` để video ghi thẳng lên NAS không tốn dung lượng máy chủ.

---

## 2. Cách thiết lập lưu video trực tiếp lên NAS

Để video clip không làm đầy dung lượng máy chủ, bạn gắn (mount) ổ đĩa chia sẻ từ NAS vào máy Linux:

### Bước 1: Mount ổ NAS vào Linux
```bash
sudo mkdir -p /mnt/nas_camera_clips
# Mount từ NAS (NFS hoặc Samba/CIFS):
sudo mount -t cifs //192.168.1.100/CameraClips /mnt/nas_camera_clips -o username=admin,password=MatKhauNAS,uid=1000,gid=1000
```
*(Để tự động mount mỗi khi khởi động lại, thêm dòng trên vào `/etc/fstab`).*

### Bước 2: Bật dòng mount NAS trong `docker-compose.yml`
Mở file `docker-compose.yml`, bỏ dấu `#` ở dòng mount NAS:
```yaml
    volumes:
      - ./CameraAI/storage:/app/storage
      - /mnt/nas_camera_clips:/app/storage/clips
```
Khi đó toàn bộ clip 10s sẽ tự động ghi thẳng vào ổ cứng NAS!

---

## 3. Cách khởi chạy hệ thống

### Trên máy Linux:
```bash
chmod +x run_docker.sh
./run_docker.sh
```
*(Hoặc chạy trực tiếp: `docker compose up -d --build`)*

### Trên máy Windows (nếu có Docker Desktop):
Nhấp đúp chuột vào file:
* [`run_docker.bat`](file:///d:/CameraV2/run_docker.bat)

---

## 4. Truy cập giao diện & Sử dụng

* **Giao diện Search & Dashboard**: 
  `http://localhost:8000/search` hoặc `http://<IP_MAY_LINUX>:8000/search`
* **Desktop App trên Linux**:
  `./run_desktop_linux.sh`
* **Desktop App trên Windows**:
  Chạy `Chay_Search_Windows.bat`
* **Kết nối PostgreSQL**:
  - Host: `<IP_MAY_LINUX>`
  - Port: `5432`
  - Database: `camera_ai`
  - Username: `camera_user`
  - Password: `camera_secure_pass168`

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
* **Cập nhật phiên bản mới**:
  ```bash
  git pull
  docker compose up -d --build
  ```
