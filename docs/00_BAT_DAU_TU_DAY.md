# Bắt đầu từ đây

Đọc và làm theo checklist này trước. Đây là tài liệu điều hướng chính; các file khác chỉ là chi tiết theo từng giai đoạn.

## Cấu trúc thư mục tài liệu

| Thư mục | Ý nghĩa | Cách dùng |
|---|---|---|
| `01_hom_nay/` | Việc đang chốt và làm trong hôm nay | Đọc đầu tiên, cập nhật thường xuyên |
| `02_dang_lam/` | Việc từ các ngày trước nhưng chưa hoàn tất | Chỉ mở khi bước hiện tại cần đến |
| `99_tam_dung_xem_lai/` | Hướng cũ/tạm dừng, chưa xóa | Không code theo các file này nếu chưa chủ động mở lại |

## Checklist hiện tại

### Giai đoạn 0 — Chốt phạm vi

- [x] Chốt mục tiêu: dùng metadata có sẵn của camera/NVR, không tự làm lại detector người.
- [x] Chốt UI: Dashboard metadata là trang mở đầu; giao diện phân tích video cũ vẫn là tab riêng.
- [x] Chốt dữ liệu: lịch sử metadata trên NVR là nguồn chính; event realtime chỉ bổ sung dữ liệu mới.
- [ ] Chốt model NVR/camera, firmware và danh sách loại metadata/event AI thực tế đã bật.
- [ ] Chốt API/NetSDK có thể truy vấn lịch sử metadata cho model/firmware đó.

### Giai đoạn 1 — Làm dữ liệu trước UI

- [ ] Lấy một mẫu metadata thật từ NVR và lưu nguyên payload để đối chiếu.
- [ ] Thiết kế SQLite event store với `event_id`, camera, channel, thời gian, loại event và metadata gốc.
- [ ] Viết adapter đồng bộ lịch sử hôm nay theo camera/kênh; có upsert chống trùng.
- [ ] Viết listener realtime để thêm event mới vào cùng store.
- [ ] Kiểm tra: mở lại app không tạo event trùng và không cần tải toàn bộ lịch sử NVR.

### Giai đoạn 2 — Clip và gợi ý video

- [ ] Từ một event, tạo job lấy clip 5 giây trước + 5 giây sau.
- [ ] Tải video qua NVR, chuyển DAV sang MP4 và lưu `clip_path` theo `event_id`.
- [ ] Làm theo `01_hom_nay/AUDIO_METADATA_INTEGRATION_PLAN.md` để tích hợp AI âm thanh Cosmos vào clip event.
- [ ] Gọi Cosmos để phân tích clip, lưu `video_suggestion` có cấu trúc.
- [ ] Kiểm tra một event mở được đúng clip và có kết quả/lỗi rõ ràng.

### Giai đoạn 3 — Dashboard mới

- [ ] Đặt Dashboard Metadata Camera là tab mặc định khi chạy app.
- [ ] Giữ tab Phân tích Video cũ hoạt động như trước.
- [ ] Render cache trước, rồi refresh khi lịch sử hôm nay đồng bộ xong.
- [ ] Hiển thị 4 KPI, AI Summary, timeline 24h, event log và bộ lọc ngày/camera/kênh.
- [ ] Mở modal xem clip 10 giây, metadata gốc và gợi ý AI theo cùng `event_id`.

### Giai đoạn 4 — AI ngôn ngữ và hoàn thiện

- [ ] Gửi metadata + gợi ý video có cấu trúc sang LLM.
- [ ] Lưu báo cáo/tóm tắt tiếng Việt; không để LLM sửa metadata nguồn.
- [ ] Thêm loading, offline, retry và empty states.
- [ ] Test end-to-end: lịch sử NVR → event → clip → Cosmos → Dashboard → tóm tắt AI.

### Giai đoạn 5 — Dọn repo (chỉ sau khi pipeline chạy)

- [ ] Đọc `01_hom_nay/CODEBASE_CLEANUP_REVIEW.md`.
- [ ] Xóa/ignore cache, log, build artifact và `NetSDK_Camera.rar` nếu đã không cần backup.
- [ ] Chốt các demo NetSDK thực sự cần, rồi bỏ demo thừa khỏi launcher trước khi xóa code.
- [ ] Archive `netSDK2/` và `cloud_ai_first/` chỉ khi xác nhận không còn runtime phụ thuộc.

## Thứ tự đọc tài liệu hôm nay

1. `01_hom_nay/CAMERA_METADATA_PIPELINE_DIRECTION.md`
2. `01_hom_nay/CAMERA_METADATA_DASHBOARD_UI_DIRECTION.md`
3. `01_hom_nay/CODEBASE_CLEANUP_REVIEW.md` — chỉ dùng ở giai đoạn dọn repo.

## Quy ước cập nhật

- Việc hoàn thành: đổi `[ ]` thành `[x]` trong file này.
- Có hướng mới: tạo file ở `01_hom_nay/` trước.
- Qua ngày nhưng vẫn chưa xong: chuyển file sang `02_dang_lam/`.
- Không làm nữa: chuyển file sang `99_tam_dung_xem_lai/`, không xóa ngay.
