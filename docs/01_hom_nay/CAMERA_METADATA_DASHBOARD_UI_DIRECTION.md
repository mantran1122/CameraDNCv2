# Định hướng giao diện: Dashboard metadata camera

## 1. Mục tiêu

Tạo một giao diện dashboard mới cho hệ thống Dahua WizMind / NVR để theo dõi metadata và sự kiện AI từ camera.

Giao diện phân tích video cũ **không bị xóa hoặc thay thế**. Ứng dụng có hai tab chính trong sidebar:

1. **Dashboard Metadata Camera** — giao diện mới, bám theo mockup.
2. **Phân tích Video (giao diện cũ)** — giữ nguyên toàn bộ luồng upload/playback/phân tích hiện có.

## 2. Khung ứng dụng

```text
Sidebar cố định
├── Logo / tên hệ thống
├── Dashboard Metadata Camera     ← tab mới
├── Phân tích Video               ← tab cũ, giữ nguyên
├── Cấu hình camera / NVR
├── Cấu hình AI / LLM
└── Trạng thái kết nối

Nội dung chính
└── Render theo tab sidebar đang chọn
```

### Quy tắc chuyển tab

- Chỉ một tab chính được hiển thị tại một thời điểm.
- Việc vào Dashboard không làm mất trạng thái/phân tích của tab cũ trong phiên hiện tại.
- Tab cũ giữ nguyên URL, xử lý video, kết quả, tìm kiếm và các nút đang có.
- Dashboard chỉ đọc dữ liệu từ event/suggestion store của pipeline metadata camera.

## 3. Dashboard Metadata Camera (tab mới)

### 3.1 Header

Hiển thị theo hàng ngang:

- Icon/logo nhỏ.
- Tên: **Dahua WizMind AI Summarizer**.
- Dòng phụ: tên NVR/camera và trạng thái kết nối, ví dụ `DHI-NVR5832-EI2 | WAN & Internet Connection Manager`.
- Chip trạng thái phía phải:
  - Xanh: `ĐÃ KẾT NỐI INTERNET / NVR ONLINE`.
  - Vàng: `ĐANG KẾT NỐI`.
  - Đỏ: `NVR OFFLINE`.
- Nút/hình đại diện người dùng ở góc phải nếu hệ thống đã có tài khoản.

### 3.2 Bốn thẻ KPI

Ngay dưới header, hiển thị 4 thẻ bằng nhau trên desktop; trên màn hình hẹp chuyển thành 2 cột hoặc 1 cột.

| Thẻ | Giá trị | Mô tả | Màu nhấn |
|---|---:|---|---|
| Tổng Metadata Hoạt động | Tổng event metadata trong khoảng lọc | Người, phương tiện, chuyển động | xanh cyan |
| Bất thường Âm thanh | Event âm thanh bất thường | La ó, cãi vã, tiếng đập phá, dB peak | đỏ |
| Bất thường Video | Event video cần chú ý | Đột nhập, vượt hàng rào, vi phạm vùng | cam/vàng |
| Metadata Con người | Event liên quan người | Diện mạo, thuộc tính nhận dạng | xanh lá/tím |

Mỗi KPI có icon nhỏ, số lớn và mô tả ngắn. Giá trị mặc định là `0` khi chưa nhận dữ liệu; không hiển thị dữ liệu minh họa như dữ liệu thật.

### 3.3 Thẻ tóm tắt AI trong ngày

Một thẻ full-width, đặt sau KPI:

- Tiêu đề: `Báo cáo Tóm tắt Hoạt động trong Ngày (Video + Audio)`.
- Nhãn: `AI SUMMARY ENGINE`.
- Nội dung là kết quả từ NLP/LLM, tổng hợp dựa trên event metadata và gợi ý video đã lưu.
- Khi không có dữ liệu: ghi rõ ngày lọc và `Không ghi nhận dữ liệu metadata hoặc sự kiện bất thường nào từ đầu ghi ...`.
- Khi LLM chưa chạy/lỗi: hiển thị trạng thái kỹ thuật ngắn; không tạo tóm tắt giả.

### 3.4 Khu vực dưới: biểu đồ + nhật ký

Desktop dùng lưới 2 cột:

- Trái (khoảng 2/3 chiều rộng): biểu đồ timeline 24 giờ.
- Phải (khoảng 1/3 chiều rộng): nhật ký sự kiện có thể cuộn.

Mobile/tablet: biểu đồ ở trên, nhật ký bên dưới.

#### A. Biểu đồ timeline 24 giờ

- Tiêu đề: `Biểu đồ Mốc thời gian Hoạt động & Bất thường (24h)`.
- Trục X: các giờ từ `00:00` đến `23:00` theo ngày đang chọn.
- Hai series:
  - `Tổng Metadata Hoạt động` — xanh/tím.
  - `Sự kiện Bất thường (Audio/Video)` — đỏ.
- Hover một điểm hiển thị số event, thời gian và phân loại.
- Click cột/điểm lọc nhật ký sự kiện theo giờ đó.
- Khi không có dữ liệu: vẫn hiện khung biểu đồ và empty state rõ ràng.

#### B. Nhật ký sự kiện và xem lại video 10 giây

- Tiêu đề: `Nhật ký Sự kiện & xem lại Video 10s`.
- Có bộ lọc nhanh:
  - `Tất cả`.
  - `Chỉ Bất thường`.
- Mỗi event card hiển thị:
  - Nhãn loại event, ví dụ `VIDEO: CROSSLINE`, `VEHICLETRAIT`, `HUMATRAIT`.
  - Thời gian event.
  - Tiêu đề tiếng Việt, ví dụ `BẤT THƯỜNG VIDEO: Phát hiện vi phạm ranh giới CrossLine tại Cam 04`.
  - Camera/kênh, ví dụ `Camera Ch 04`.
  - Nút `Xem 10s Clip` chỉ xuất hiện khi clip đã sẵn sàng.
  - Trạng thái `Đang lấy clip`, `Đang phân tích`, `Lỗi tải clip` khi chưa sẵn sàng.
- Click card hoặc nút clip mở modal/panel xem video; luôn kèm metadata nguồn và gợi ý AI tương ứng.

## 4. Hành vi dữ liệu

Dashboard đọc các record theo `event_id` từ pipeline trong `CAMERA_METADATA_PIPELINE_DIRECTION.md`:

```text
camera_event
  ├── hiển thị KPI, timeline, event log
  ├── clip_path → nút xem 10s clip
  └── video_suggestion → phần gợi ý trong chi tiết event

video_suggestion của nhiều event
  └── NLP/LLM → báo cáo tóm tắt trong ngày
```

Tất cả số liệu phải lọc theo:

- ngày (mặc định hôm nay);
- camera/NVR đang chọn;
- tùy chọn kênh camera;
- tùy chọn chỉ bất thường.

## 5. Sidebar

Sidebar giữ phong cách và chức năng ban đầu của app, chỉ bổ sung điều hướng rõ ràng:

```text
HỆ THỐNG CAMERA AI
────────────────────────
▣ Dashboard Metadata Camera
▣ Phân tích Video
────────────────────────
Thiết bị đang chọn: NVR ...
Camera/kênh: Tất cả / Ch 01 / Ch 02 ...
Ngày: [date picker]
────────────────────────
Trạng thái: ● NVR online
```

- `Dashboard Metadata Camera` là trang mặc định khi chạy app, kể cả khi NVR chưa kết nối; khi đó trang hiển thị trạng thái offline/retry thay vì tự chuyển sang tab cũ.
- `Phân tích Video` mở đúng giao diện cũ, không thiết kế lại trong phạm vi này.
- Filter camera/kênh/ngày trong sidebar áp dụng cho Dashboard; tab cũ chỉ dùng chúng nếu đã có cơ chế tương thích sẵn.

## 6. Hệ màu và kiểu dáng

Theo mockup, dùng dark dashboard:

- Nền trang: navy gần đen (`#090D1C` đến `#10172B`).
- Thẻ: xanh navy đậm, viền sáng rất nhẹ.
- Chữ chính: trắng/xám rất sáng; chữ phụ: xám xanh.
- Nhấn: cyan/xanh dương cho metadata, đỏ cho audio bất thường, cam cho video bất thường, xanh lá/tím cho thuộc tính người.
- Bo góc thẻ vừa phải (khoảng 14–18px), padding rộng, shadow nhẹ.
- Không dùng gradient hoặc animation gây phân tâm; cập nhật trạng thái bằng chip và loading skeleton nhỏ.
- Bảo đảm tương phản đọc được và không chỉ phân biệt trạng thái bằng màu.

## 7. Phạm vi triển khai UI theo thứ tự

1. Khi app khởi động, chọn `Dashboard Metadata Camera`; sidebar vẫn cho chuyển sang tab cũ.
2. Dựng layout Dashboard với loading/empty/error states đúng trạng thái.
3. Nạp dữ liệu lịch sử metadata của ngày đang chọn từ NVR/camera, rồi cập nhật KPI, timeline, event log.
4. Nối cache/event store nội bộ để Dashboard mở lại nhanh và vẫn xem được dữ liệu đã đồng bộ khi NVR tạm offline.
5. Nối stream event realtime để bổ sung record mới vào Dashboard mà không tải lại cả ngày.
6. Nối modal xem clip 10 giây và metadata/gợi ý chi tiết.
7. Nối AI Summary Engine sau khi `video_suggestion` đã có dữ liệu thật.
8. Hoàn thiện responsive, empty/error/loading states.

## 8. Tiêu chí nghiệm thu

- Người dùng đổi được giữa Dashboard mới và giao diện phân tích cũ từ sidebar.
- Giao diện cũ vẫn chạy được như trước.
- Dashboard hiển thị đúng 4 KPI, báo cáo ngày, timeline và event log.
- Event thực tế mở được clip 10 giây khi job hoàn thành.
- Không có event thì UI rõ ràng, đẹp và không tạo số liệu/tóm tắt giả.
- Chi tiết event luôn truy được metadata gốc, clip và gợi ý AI qua cùng `event_id`.
