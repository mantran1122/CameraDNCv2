# 📋 TỔNG HỢP Ý KIẾN GÓP Ý CỦA SẾP & KẾ HOẠCH TRIỂN KHAI (CHECKLIST)

> **Dự án:** CameraDNCv2 - Camera AI & NVR Vision Search  
> **Ngày ghi nhận:** 29/09/2026  
> **Trạng thái:** Đã ghi nhận & Sẵn sàng triển khai  

---

## 🎯 DANH SÁCH Ý KIẾN GÓP Ý & YÊU CẦU

### 1. [UI/UX] Cải tiến Khung nhập Chat (Chat Input & Auto-grow)
* **Ý kiến của sếp:**
  > Khung chat khi gõ chữ không kéo dài ngang mà sẽ tự động xuống dòng. Có thể tham khảo giao diện chat bot hiện đại (như Grok / Telegram / AI Bot) để tối ưu giao diện nhưng **tuyệt đối không làm đổi bảng màu sắc chủ đạo** của hệ thống.
* **Nguyên nhân kỹ thuật:** Ô input hiện tại sử dụng thẻ `<input type="text">` đơn dòng khiến văn bản dài bị tràn theo chiều ngang, không hiển thị trực quan và khó soạn câu hỏi dài.
* **Giải pháp:**
  * Chuyển đổi `<input type="text">` sang `<textarea>` tự co giãn chiều cao (auto-growing textarea) với chiều cao tối đa (max-height ~120px-150px) kèm thanh cuộn mềm mượt khi gõ nhiều dòng.
  * Hỗ trợ phím tắt chuẩn: `Enter` để gửi tin nhắn; `Shift + Enter` để xuống dòng trong ô gõ.
  * Thiết kế lại khung nhập liệu bo góc (pill/rounded container), icon nút gửi (Send) đặt gọn gàng phía góc phải.
  * Bảo lưu 100% theme màu Dark/Metropolis Cyan-Blue hiện có, chỉ tinh chỉnh cấu trúc layout và bóng/border.

---

### 2. [UI Cleanup] Ẩn toàn bộ nút bấm chưa có tính năng thực tế
* **Ý kiến của sếp:**
  > Các nút nào chưa có chức năng thì ẩn đi, không hiển thị ra làm gì để người dùng bấm lung tung.
* **Nguyên nhân kỹ thuật:** Một số nút mẫu (mockup/placeholder/nút tính năng đang phát triển) vẫn xuất hiện trên giao diện khiến người dùng click vào nhưng không thấy phản hồi hoặc gây bối rối.
* **Giải pháp:**
  * Rà soát toàn bộ các button, badge, switch trên Dashboard chính (`index.html`), trang Search (`search.html`), và các Modal.
  * Ẩn hoặc loại bỏ các nút chức năng chưa có API hỗ trợ (hoặc chưa hoàn thiện logic).
  * Đảm bảo mọi nút còn lại trên màn hình đều có tác vụ thực thi cụ thể, phản hồi trạng thái rõ ràng (loading, toast message, popup).

---

### 3. [Bảo mật & Quyền truy cập] Phân quyền Camera theo từng Tài khoản (Channel-Level RBAC)
* **Ý kiến của sếp:**
  > Hiện logic đang có vấn đề: Dù có tài khoản phân quyền nhưng khi admin cấu hình cam trên máy chủ thì tài khoản cấp thấp vẫn xem được mọi camera. Hiện tại có rất nhiều camera nhạy cảm (phòng họp, tài chính, ban lãnh đạo...), cần đổi logic bảo mật chặt chẽ.
* **Thống nhất giải pháp:** Áp dụng **Cách 1: Gán quyền Camera cụ thể cho từng User (Whitelist Allowed Channels)**.
* **Giải pháp chi tiết:**
  * **Cơ chế tài khoản:**
    * **Admin / Quản trị viên:** Toàn quyền cấu hình NVR, quản lý người dùng và xem toàn bộ camera (`allowed_channels = ["*"]`).
    * **Viewer / Sub-user:** Được cấu hình danh sách camera cụ thể được phép xem (Ví dụ: `allowed_channels = [1, 2, 5]`).
  * **Bảo mật đa tầng Backend (Bắt buộc):**
    1. **API Sự kiện (`/api/events`):** Tự động lọc theo session user đăng nhập: `WHERE channel IN (:allowed_channels)`.
    2. **API Phát Clip (`/api/clips/...`):** Kiểm tra quyền sở hữu kênh trước khi trả video stream, từ chối trả về `403 Forbidden` nếu không có quyền.
    3. **AI Search & Chatbot (`/api/vss/search` & Vision Agent):** AI chỉ truy vấn và trả lời các sự kiện thuộc danh sách camera user được phép xem.
    4. **WebSocket Thông báo (`/ws/events`):** Chỉ broadcast sự kiện realtime của các kênh user được phân quyền.
  * **Quản trị:** Trong modal Quản lý Tài khoản (User Management) của Admin, thêm bảng checkbox chọn các Camera phân quyền cho từng tài khoản con.

---

### 4. [Hiển thị Kênh] Tên Camera rõ ràng & Tải động Dropdown theo quyền User
* **Ý kiến của sếp:**
  > Tên camera trên giao diện chọn cam khi xem ở search phải có tên rõ ràng và load được mọi camera mà tài khoản đó có quyền xem chứ không phải tài khoản nào drop cũng có 4 camera. Được xem bao nhiêu drop bấy nhiêu và chỉ drop góc nhìn main.
* **Nguyên nhân kỹ thuật:** Hiện tại một số vị trí đang hardcode danh sách 4 camera (`[11, 18, 19, 20]`) và tên camera hiển thị chưa đầy đủ ngữ cảnh khu vực.
* **Giải pháp:**
  * **Tên Camera chuẩn hóa:** Hiển thị tên đầy đủ kèm mã kênh và khu vực thực tế (Ví dụ: `D11 - 11.T1. QUẢN LÝ HSSV`, `D18 - 18.T1. SẢNH CAM1`, `D07 - 7.T1. TÀI CHÍNH-KẾ HOẠCH`...).
  * **Tải động (Dynamic Loading):** Dropdown / Select box tại trang Search và Live View chỉ nạp danh sách các camera nằm trong `allowed_channels` của tài khoản đang đăng nhập. User có quyền 2 camera thì dropdown chỉ có đúng 2 camera; user có quyền 10 camera thì hiển thị đủ 10 camera.
  * **Chỉ lấy góc nhìn Main (Main Stream):** Chỉ tải luồng chính (Main Stream), không lấy các luồng phụ (sub-stream) gây trùng lặp danh sách kênh.

---

## 📝 CHECKLIST CÔNG VIỆC TRIỂN KHAI

### Phase 1: Giao diện Chat & Dọn dẹp UI (#1 & #2)
- [x] **1.1. Cải tiến Khung nhập Chat & Nút thu Sidebar (#1 & Góp ý ảnh của Boss):**
  - [x] Thay đổi nút thu gọn sidebar từ mũi tên sang nút icon hamburger (3 gạch ngang) đặt cạnh nhãn "Vision Agent" theo mẫu ảnh của Boss.
  - [x] Thay thế `<input id="vss-agent-input">` bằng thẻ `<textarea>` trong `index.html`.
  - [x] Thêm CSS tự dãn chiều cao (auto-grow lên tới 140px), word-break và white-space: pre-wrap cho chat bubbles.
  - [x] Xử lý sự kiện bàn phím: `Enter` gửi tin nhắn, `Shift + Enter` xuống dòng mượt mà.
  - [x] Tinh chỉnh layout nút Send nằm góc dưới bên phải khung nhập, giữ nguyên 100% palette màu hiện hành.
- [x] **1.2. Rà soát & Ẩn các nút bấm chưa có tính năng:**
  - [x] Rà soát và ẩn thanh phản hồi mẫu (thumbs up/down, share, feedback) chưa có API trên giao diện Chat.
  - [x] Ẩn nút cấu hình Model Parameters (icon bánh răng) chưa có chức năng.
  - [x] Chuyển đổi nút hamburger bên cạnh "Vision Agent" làm nút thu/mở sidebar chính thức và loại bỏ nút mũi tên thừa thãi theo yêu cầu của Boss.

### Phase 2: Phân quyền Camera tầng Lõi Backend (#3)
- [ ] **2.1. Cấu trúc dữ liệu Người dùng & Quyền Kênh:**
  - [ ] Thêm trường `allowed_channels: List[int]` vào model người dùng (`SubUserModel`, `users.json` / Database).
  - [ ] Cập nhật API `POST /api/admin/users` và `PUT /api/admin/users/{username}` để lưu danh sách kênh được phân quyền.
- [ ] **2.2. Kiểm soát truy cập API (Access Control Enforcement):**
  - [ ] Chặn API `/api/events`: Lọc chỉ trả về sự kiện thuộc `allowed_channels` của user.
  - [ ] Chặn API `/api/clips/{clip_filename}` và stream video: Kiểm tra kênh của clip, chặn `403` nếu không có quyền.
  - [ ] Chặn API `/api/vss/search` & Vision Agent Chat: Ép điều kiện lọc kênh theo quyền của user trước khi AI truy vấn dữ liệu.
  - [ ] Chặn WebSocket `/ws/events`: Phân loại kết nối và chỉ bắn sự kiện realtime thuộc các kênh user được phép.

### Phase 3: Quản lý Phân quyền & Tải động Danh sách Camera (#3 & #4)
- [ ] **3.1. Giao diện Quản lý Phân quyền của Admin:**
  - [ ] Bổ sung bảng chọn Kênh (Checkbox Grid 1-32) khi Admin tạo / sửa tài khoản con.
  - [ ] Hiển thị danh sách kênh được phân quyền trong bảng danh sách người dùng.
- [ ] **3.2. Chuẩn hóa Tên Camera & Dynamic Dropdown tại Search / Live View:**
  - [ ] Cung cấp API `/api/user/allowed-cameras` trả về danh sách camera hợp lệ của user hiện tại kèm tên chuẩn (`Dxx - Tên vị trí`).
  - [ ] Loại bỏ hoàn toàn logic hardcode 4 camera (`[11, 18, 19, 20]`).
  - [ ] Tự động fill dropdown/select camera theo đúng quyền của tài khoản (được xem bao nhiêu thì dropdown bấy nhiêu).
  - [ ] Đảm bảo chỉ liên kết luồng Main (Main Stream / Main View), loại bỏ trùng lặp sub-stream.

### Phase 4: Kiểm thử & Nghiệm thu
- [ ] **4.1. Kiểm thử UI Chat:** Thử gõ văn bản dài, gõ nhiều đoạn với Shift+Enter, kiểm tra màu sắc trên dark mode.
- [ ] **4.2. Kiểm thử Bảo mật Kênh:**
  - [ ] Đăng nhập bằng tài khoản con (ví dụ chỉ có Cam 11).
  - [ ] Kiểm tra xem dropdown chỉ có đúng Cam 11.
  - [ ] Kiểm tra Search & Chat AI chỉ tìm thấy sự kiện Cam 11.
  - [ ] Dùng link trực tiếp mở video của Cam khác -> Xác nhận bị chặn `403`.
- [ ] **4.3. Báo cáo nghiệm thu hoàn tất cho Sếp.**
