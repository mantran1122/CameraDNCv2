# Kế hoạch tích hợp đầu ghi Dahua với Cosmos

## Mục tiêu

Cho phép người dùng làm ba việc trong cùng một hệ thống:

1. Xem trực tiếp camera từ đầu ghi Dahua.
2. Phân tích luồng camera gần thời gian thực bằng Cosmos và nhận cảnh báo.
3. Chọn khoảng thời gian bản ghi (playback), tải video từ đầu ghi, rồi phân tích bằng Cosmos.

## Kết luận kỹ thuật

Khả thi với code hiện có:

- `NetSDK_Camera` đã đăng nhập đầu ghi, xem live (`RealPlayEx`), playback theo thời gian (`PlayBackByTimeEx2`) và tải video theo thời gian (`DownloadByTimeEx`).
- `cosmos_code_base/live_service.py` đã có `POST /analyze`, nhận một ảnh JPEG và trả kết quả JSON.
- Pipeline trong `cosmos_code_base` đã phân tích video file theo chunk, phù hợp cho playback dài.

`NetSDK_Camera` nên là lớp kết nối Dahua. Cosmos nên giữ độc lập như một service phân tích để sau này có thể bổ sung RTSP/ONVIF hoặc hãng đầu ghi khác mà không sửa phần AI.

## Kiến trúc đề xuất

```text
                           +---------------------+
                           |  Đầu ghi Dahua / NVR |
                           +----------+----------+
                                      |
             +------------------------+------------------------+
             |                                                 |
             v                                                 v
      [Live preview]                                  [Playback / download]
             |                                                 |
             v                                                 v
      Màn hình người dùng                             File video theo thời gian
             |                                                 |
             v                                                 v
  Lấy mẫu + lọc chuyển động                         Hàng đợi job phân tích
             |                                                 |
             +------------------------+------------------------+
                                      v
                              Cosmos inference
                                      |
                                      v
                  Sự kiện, timestamp, mức độ rủi ro, clip/frame
```

## Chức năng 1 — Xem camera trực tiếp

### Yêu cầu

- Đăng nhập đầu ghi: IP, cổng SDK (thường `37777`), username, password.
- Lấy danh sách kênh camera.
- Chọn camera và main-stream/sub-stream.
- Bắt đầu/dừng preview và hiển thị trạng thái kết nối.

### Khuyến nghị

- Mặc định dùng **sub-stream** cho lưới nhiều camera để giảm băng thông và tải decode.
- Chỉ dùng **main-stream** cho camera người dùng đang phóng to hoặc cần xem chi tiết.
- Thông tin đăng nhập không hard-code; lưu bằng biến môi trường hoặc secret store. Không ghi password vào log/API response.

## Chức năng 2 — Live camera đến Cosmos

### Không gửi toàn bộ frame

Không gửi video live 25 fps trực tiếp cho Cosmos. Một lần inference có thể mất vài giây, nên hàng đợi sẽ tăng vô hạn, tạo kết quả lỗi thời và tốn GPU.

### Chiến lược đề xuất

1. Lấy frame từ live stream.
2. Chạy motion gate nhẹ bằng OpenCV hoặc so sánh frame liên tiếp.
3. Chỉ khi có chuyển động (hoặc theo chu kỳ) mới tạo job Cosmos.
4. JPEG frame được gửi tới `POST /analyze` của `live_service.py`.
5. Nếu Cosmos đang bận, bỏ frame cũ và chỉ giữ frame mới nhất của từng camera.
6. Ghi kết quả với `camera_id`, `captured_at`, `received_at`, `risk_level`, `summary` và đường dẫn frame/clip nếu có.

### Thông số mặc định nên dùng

| Tham số | Giá trị khởi đầu | Ghi chú |
|---|---:|---|
| Chu kỳ lấy mẫu khi có chuyển động | 2–5 giây | Điều chỉnh theo tốc độ GPU |
| Chu kỳ heartbeat khi không chuyển động | 30–60 giây | Kiểm tra bối cảnh/camera còn hoạt động |
| Job Cosmos đồng thời / camera | 1 | Không tạo backlog theo camera |
| Queue toàn hệ thống | Có giới hạn | Đầy thì bỏ job live cũ, không bỏ playback chủ động |
| Clip bằng chứng | 15–30 giây trước/sau sự kiện | Lưu khi có cảnh báo đủ ngưỡng |

### Kết quả UI

- Ảnh live và trạng thái `Đã kết nối / Mất kết nối / Đang phân tích`.
- Dòng sự kiện mới nhất kèm timestamp và độ rủi ro.
- Cảnh báo chỉ khi vượt ngưỡng; không hiện từng kết quả bình thường để tránh nhiễu.
- Link xem frame hoặc clip bằng chứng.

## Chức năng 3 — Playback đến Cosmos

### Luồng xử lý

1. Người dùng chọn camera, thời điểm bắt đầu và kết thúc.
2. Gọi `DownloadByTimeEx` để tải bản ghi từ đầu ghi về thư mục tạm.
3. Chia yêu cầu dài thành các clip 5–15 phút.
4. Đưa từng clip vào hàng đợi phân tích video của Cosmos.
5. Pipeline video lấy mẫu/chia chunk và trả các sự kiện theo timestamp.
6. Lưu kết quả, hiển thị tiến độ và cho phép mở video đúng vị trí xảy ra sự kiện.

### Vì sao cần chia clip

- Một video vài chục phút có thể lớn và thời gian inference dài.
- Có thể retry một clip lỗi thay vì chạy lại toàn bộ.
- Người dùng thấy kết quả đầu tiên sớm hơn.
- Dễ kiểm soát dung lượng và dọn file tạm.

### Quy tắc job playback

- Playback là batch job: không block UI.
- Có trạng thái: `queued`, `downloading`, `downloaded`, `analyzing`, `completed`, `failed`, `cancelled`.
- Có phần trăm tải và phần trăm phân tích.
- Cho phép hủy; hủy phải dừng download/worker và xóa file tạm an toàn.
- Giữ file nguồn theo chính sách cấu hình; mặc định chỉ giữ clip sự kiện và metadata, xóa video tạm sau khi hoàn tất.

## Dữ liệu tối thiểu cần lưu

```text
Camera
- id, display_name, dahua_channel, stream_type, enabled

AnalysisJob
- id, type (live | playback), camera_id, start_at, end_at
- status, progress, created_at, started_at, finished_at, error
- source_path, temporary_path

AnalysisEvent
- id, job_id, camera_id, captured_at, risk_level, summary
- frame_path, clip_path, raw_result
```

## Thứ tự triển khai (MVP)

1. **Kết nối Dahua**: form cấu hình, login, logout, liệt kê camera và kiểm tra quyền.
2. **Live preview**: chọn camera, main/sub-stream, start/stop và trạng thái kết nối.
3. **Live sampling**: lấy frame theo chu kỳ, gửi JPEG sang Cosmos, hiển thị kết quả mới nhất.
4. **Motion gate + queue**: giảm chi phí inference, chống backlog, tự reconnect.
5. **Playback download**: chọn khoảng thời gian, tải clip và hiển thị tiến độ.
6. **Playback analysis**: tự động đưa clip tải về vào pipeline Cosmos theo hàng đợi.
7. **Lịch sử/cảnh báo**: lọc theo camera, thời gian, mức rủi ro; mở frame/clip bằng chứng.

## Tiêu chí nghiệm thu

### Live

- Login thành công và hiển thị đúng số camera.
- Xem được main-stream/sub-stream ít nhất một camera.
- Dừng preview/logout không rò rỉ handle SDK.
- Mất kết nối được báo trên UI và có thể reconnect.
- Khi AI bật, kết quả live có `camera_id` và timestamp đúng frame.

### Playback

- Chọn một khoảng 1–5 phút, tải thành công file video.
- Job tự chuyển sang phân tích sau khi tải xong.
- Kết quả mở được video/frame đúng timestamp.
- Hủy job không làm hỏng database hoặc giữ file tạm không cần thiết.

## Rủi ro và cách xử lý

| Rủi ro | Cách xử lý |
|---|---|
| Cosmos chậm hơn live stream | Sampling, motion gate, queue giới hạn và drop frame cũ |
| Nhiều camera làm quá tải GPU | Giới hạn worker toàn hệ thống; ưu tiên camera/alert quan trọng |
| Mất mạng đầu ghi | Auto reconnect, hiển thị trạng thái, retry theo backoff |
| Video download codec lạ | Dùng FFmpeg chuẩn hóa sang H.264 MP4 trước phân tích |
| File playback quá lớn | Chia khoảng thời gian thành clip 5–15 phút; dọn file tạm |
| Lộ thông tin đầu ghi | Secret store/env vars, che password trong log, phân quyền người dùng |

## Quyết định kiến trúc

- Dùng **NetSDK Dahua** cho live, playback và download bản ghi.
- Dùng **Cosmos live service** cho frame live đã lấy mẫu.
- Dùng **pipeline Cosmos video hiện tại** cho playback/download đã thành file.
- Tách các tác vụ tải/phân tích thành background worker + queue.
- Không đưa password đầu ghi vào source code hoặc Markdown cấu hình commit lên Git.
