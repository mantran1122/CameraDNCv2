# HƯỚNG DẪN CÀI ĐẶT HỆ THỐNG CAMERA AI DNC LÊN MÁY KHÁC

Tài liệu này hướng dẫn chi tiết từng bước để triển khai hệ thống **Camera AI DNC (Dahua NVR AI Summarizer & Search Studio)** lên máy tính của cán bộ, máy phòng trực hoặc máy chủ khác.

---

## I. YÊU CẦU TRƯỚC KHI CÀI ĐẶT

Hệ thống hỗ trợ cả **Windows (10 / 11)** và **Linux (Ubuntu 20.04 / 22.04 / 24.04)**. Bạn chọn **1 trong 2 cách cài đặt**:

* **Cách 1 (Khuyên dùng - Nhanh nhất):** Chạy bằng **Docker**. Chỉ cần máy có [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows) hoặc Docker Engine (Linux). Không cần cài đặt thư viện Python phức tạp.
* **Cách 2:** Chạy bằng **Python thuần** (nếu máy tính không hỗ trợ hoặc không muốn cài Docker).

---

## II. CÁCH 1: CÀI ĐẶT & CHẠY BẰNG DOCKER (KHUYÊN DÙNG)

### Bước 1: Tải mã nguồn về máy mới

Mở **Terminal** (hoặc PowerShell / Command Prompt trên Windows) và chạy lệnh:
```bash
git clone https://github.com/mantran1122/CameraDNCv2.git
cd CameraDNCv2
```
*(Nếu đã có mã nguồn từ trước, chỉ cần vào thư mục và gõ: `git pull origin main`)*

### Bước 2: Khởi động hệ thống (Chỉ 1 Click)

#### 👉 Dành cho máy Windows:
1. Đảm bảo phần mềm **Docker Desktop** đang chạy (biểu tượng cá voi màu xanh ở góc màn hình).
2. Nhấp đúp chuột vào file:
   📁 **`Chay_Docker_Windows.bat`**
3. Script sẽ tự động:
   * Build image và bật cụm container: **PostgreSQL** (Database lưu trữ) + **CameraAI** (FastAPI & Vision Studio).
   * Tự động mở trình duyệt web lên địa chỉ: `http://localhost:8000/login`.

#### 👉 Dành cho máy Linux / Ubuntu Server:
Chạy lệnh:
```bash
chmod +x Chay_Docker_Linux.sh
./Chay_Docker_Linux.sh
```
*(Hoặc gõ trực tiếp: `docker compose up -d --build`)*

---

## III. CÁCH 2: CÀI ĐẶT BẰNG PYTHON THUẦN (KHÔNG DÙNG DOCKER)

Nếu máy tính cán bộ không có Docker, bạn làm theo các bước sau:

### Bước 1: Cài đặt Python
* Cài đặt **Python 3.10 hoặc 3.11** từ trang chủ [python.org](https://www.python.org/downloads/).
* ⚠️ **LƯU Ý QUAN TRỌNG:** Trong quá trình cài, nhớ tích chọn ô **`Add python.exe to PATH`**.

### Bước 2: Cài đặt các thư viện phụ thuộc
Mở CMD / PowerShell tại thư mục dự án và chạy:
```bash
cd CameraAI
pip install -r requirements.txt
cd ..
```

### Bước 3: Khởi động ứng dụng Desktop
Trở về thư mục gốc `CameraDNCv2`, nhấp đúp chuột vào:
📁 **`Chay_Search_Windows.bat`**
*(Cửa sổ ứng dụng Desktop độc lập sẽ mở lên màn hình đăng nhập hệ thống).*

---

## IV. THÔNG TIN ĐĂNG NHẬP & PHÂN QUYỀN

Hệ thống đã được tích hợp cơ chế phân quyền bảo mật **RBAC (Role-Based Access Control)**:

### 1. Tài khoản bàn giao cho Cán bộ / Nhân viên trực:
* **Tên đăng nhập (Username):** `user`
* **Mật khẩu (Password):** `123`
* **Quyền hạn:**
  * Xem trực tiếp luồng camera (Live Stream).
  * Tra cứu sự kiện, tìm kiếm người, phương tiện bằng AI (`/search`).
  * Xem báo cáo tóm tắt ngày và video clip.
  * 🔒 **BẢO MẬT:** Nút **"Cấu hình Quản lý Camera & NVR" hoàn toàn BỊ ẨN**, cán bộ không thể thay đổi thông số kỹ thuật.

### 2. Tài khoản Quản trị viên (Dành riêng cho Kỹ thuật viên / Admin):
* **Tên đăng nhập (Username):** `admin`
* **Mật khẩu (Password):** `namcantho@168`
* **Quyền hạn:**
  * Toàn quyền quản trị hệ thống.
  * Mở tab Cấu hình NVR, IP, Port, DDNS, AI LLM Prompts.
  * Cấp thêm hoặc xóa tài khoản con.

### 3. Phím tắt bí mật mở Cấu hình khẩn cấp:
Khi cán bộ đang đăng nhập tài khoản `user`, nếu kỹ thuật viên cần vào cấu hình:
1. Nhấn tổ hợp phím bí mật: <kbd>Ctrl</kbd> + <kbd>Shift</kbd> + <kbd>C</kbd>.
2. Nhập tài khoản `admin` và mật khẩu `namcantho@168`.
3. Tab Cấu hình NVR sẽ lập tức mở khóa. Sau khi cấu hình xong, bấm **"🔒 Khóa & Ẩn"** để trả lại màn hình cho cán bộ.

---

## V. CÁCH CẤP THÊM TÀI KHOẢN CON CHO CÁN BỘ MỚI

Nếu có thêm cán bộ hoặc nhân viên bảo vệ mới cần tài khoản:
1. Đăng nhập bằng tài khoản **`admin`**.
2. Vào mục **"Cấu hình Quản lý Camera"**.
3. Cuộn xuống thẻ **"Quản lý Tài khoản & Cấp quyền Tài khoản con (RBAC)"**.
4. Điền các thông tin:
   * **Tên đăng nhập:** ví dụ `baove_khuB`
   * **Mật khẩu:** ví dụ `456`
   * **Họ tên / Đơn vị:** ví dụ `Tổ Trực Bảo Vệ Khu B`
   * **Vai trò:** Chọn `Người xem (Viewer)` hoặc `Điều hành viên (Operator)`.
5. Bấm nút **`+ Cấp tài khoản`**. Tài khoản mới có thể đăng nhập ngay lập tức!

---

## VI. CÁC LỆNH QUẢN LÝ DOCKER HỮU ÍCH

* **Xem log hệ thống đang chạy thời gian thực:**
  ```bash
  docker compose logs -f
  ```
* **Khởi động lại hệ thống:**
  ```bash
  docker compose restart
  ```
* **Tắt hệ thống:**
  ```bash
  docker compose down
  ```
* **Cập nhật khi có code mới trên Git:**
  ```bash
  git pull origin main
  docker compose up -d --build
  ```

---

## VII. XỬ LÝ SỰ CỐ THƯỜNG GẶP (TROUBLESHOOTING)

| Hiện tượng | Nguyên nhân | Cách khắc phục |
| :--- | :--- | :--- |
| Chạy file `.bat` báo lỗi không tìm thấy Docker | Docker Desktop chưa được cài hoặc chưa mở | Mở phần mềm Docker Desktop trên máy tính, chờ biểu tượng chuyển sang màu xanh rồi chạy lại file `.bat`. |
| Báo lỗi cổng 8000 đã bị chiếm dụng | Có ứng dụng khác đang dùng port 8000 | Tắt ứng dụng đang dùng port 8000 hoặc khởi động lại máy. |
| Camera không lên hình hoặc báo Offline | Mạng Internet hoặc IP DDNS đầu ghi bị thay đổi | Đăng nhập bằng tài khoản `admin`, vào tab Cấu hình kiểm tra IP/Port NVR và bấm **"Kiểm tra kết nối"**. |

