# Báo cáo tiến độ — Pilot AI Phòng Quản lý Học sinh Sinh viên

Ngày cập nhật: 2026-08-21

## Mục tiêu đã thống nhất

Pilot triển khai cho một camera. Các quyết định về bàn trực, vắng mặt, ra/vào
và khu vực chờ dựa trên CV theo thời gian: detector người → tracker → vùng
camera → rule engine. Cosmos chỉ viết báo cáo tiếng Việt từ event đã được rule
engine xác minh; không dùng VLM để tự đếm người hoặc suy luận thời lượng.

## Hạng mục đã hoàn thành

1. Camera profile
   - Tạo `configs/cameras/student_affairs_pilot.yaml` với vùng cửa, vùng chờ,
     hai bàn trực và ngưỡng thời gian mẫu.
   - Tọa độ được chuẩn hoá 0.0–1.0 để hiệu chỉnh theo camera, không hard-code
     theo góc quay.

2. Lõi rule engine
   - Thêm `student_affairs/config.py` để đọc và kiểm tra YAML: polygon, ID bàn,
     số nhân sự và ngưỡng hợp lệ.
   - Thêm `student_affairs/zones.py` để gán vùng theo điểm chân bounding box.
   - Thêm `student_affairs/rules.py` với trạng thái bàn `covered`, `overstaff`,
     `uncovered_pending`, `uncovered_alert`; cảnh báo đông và chống lặp alert.
   - Khi camera đổi góc, rule engine trả `needs_recalibration`, xoá trạng thái
     tạm và không tiếp tục áp các vùng cũ.

3. Detector đồng phục
   - `YellowUniformDetector.detect_people()` hiện trả dữ liệu từng người gồm
     bbox, confidence, yellow score và blue score.
   - Giữ `detect()` dạng tổng hợp để không làm hỏng endpoint tuyển sinh cũ.
   - Thêm adapter `student_affairs/detector.py`, xuất candidate có điểm chân
     chuẩn hoá để truyền sang tracker.

4. Prompt và phụ thuộc
   - Thêm profile `student_affairs`, quy định chỉ diễn giải facts đã xác minh.
   - Bổ sung PyYAML để đọc camera profile.

5. Tracker theo camera
   - Thêm `student_affairs/tracker.py`: tracker in-memory riêng cho mỗi `camera_id`,
     gán ID theo IoU/khoảng cách và loại track hết hạn theo thời gian.
   - Tách `CameraTrackerRegistry` để không bao giờ dùng chung state giữa hai camera.

6. Kiểm thử offline
   - Thêm `student_affairs/offline.py`: CLI đọc video ghi sẵn, chạy detector → tracker
     → rule engine và xuất MP4 overlay `track_id`/zone/trạng thái cùng JSONL event tuỳ chọn.

## Kiểm thử đã chạy

`python -m unittest tests.test_student_affairs_rules tests.test_student_affairs_detector tests.test_student_affairs_tracker`

Test bao phủ ngưỡng báo vắng, chống lặp alert, bàn có nhân viên, scene-change,
dữ liệu detector, giữ ID khi di chuyển nhẹ, hết hạn track, cách ly state giữa camera
và pipeline/overlay offline.

## Việc tiếp theo

- Xây state machine qua cửa: chỉ xác nhận `outside` khi có chuỗi bằng chứng;
  mất track giữa phòng chỉ ghi `uncertain_lost_track`.
- Tạo endpoint pilot nhận frame và trả JSON contract; giữ `/analyze` hiện tại
  cho các profile cũ.
- Sau đó mới tích hợp NetSDK ở 1–2 FPS, replay/UI và Cosmos theo event thay đổi.

## Thông tin còn cần chốt

Camera/kênh pilot, số bàn và các ngưỡng thực tế, khả năng camera nhìn rõ cửa,
quy trình xác nhận lại zone sau xoay/zoom, cùng quyền sử dụng audio.
