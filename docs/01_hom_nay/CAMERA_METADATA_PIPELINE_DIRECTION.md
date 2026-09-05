# Định hướng: Pipeline metadata từ camera → video → gợi ý → AI ngôn ngữ

## 1. Mục tiêu

Tận dụng **metadata/sự kiện do camera hoặc đầu ghi tạo sẵn** (ví dụ: phát hiện người, xâm nhập, khuôn mặt, chuyển động). Hệ thống của ta **không xây lại model phát hiện người**.

Khi có một sự kiện hợp lệ, hệ thống sẽ:

1. Nhận và lưu metadata thô từ camera.
2. Lấy đúng clip ghi hình 10 giây quanh thời điểm sự kiện.
3. Chạy mô hình video trên clip đó để tạo gợi ý có cấu trúc.
4. Lưu clip, metadata và gợi ý với cùng một `event_id`.
5. Chuyển gợi ý đã lưu sang AI xử lý ngôn ngữ tự nhiên (LLM) để tạo cảnh báo, tóm tắt hoặc trả lời truy vấn.

## 2. Nguyên tắc không đi lệch hướng

- **Camera là nguồn phát hiện ban đầu.** Chỉ xử lý khi camera gửi event; không quét liên tục toàn bộ luồng để tự phát hiện người.
- **Giữ metadata nguyên gốc.** Không thay thế metadata camera bằng suy đoán của AI.
- **Video model chỉ làm rõ ngữ cảnh.** Ví dụ: diễn biến, số người ước lượng, hành vi cần chú ý, mức độ ưu tiên.
- **LLM chỉ nhận dữ liệu đã cấu trúc.** LLM không nhận toàn bộ stream camera; nó nhận metadata và gợi ý đã lưu.
- Mọi dữ liệu cùng sự kiện phải nối được bằng một `event_id` duy nhất.
- Không xóa clip hay kết quả tự động ở giai đoạn đầu; chính sách lưu trữ sẽ chốt sau khi pipeline chạy ổn định.

## 3. Nguồn dữ liệu và nguyên tắc đồng bộ

Metadata có sẵn trong lịch sử của camera/NVR là **nguồn dữ liệu chính cho Dashboard**. Listener realtime chỉ dùng để nhận các event phát sinh sau thời điểm Dashboard đã mở; nó không thay thế lịch sử trên thiết bị.

Mỗi camera/NVR cần có adapter truy vấn lịch sử phù hợp với firmware/SDK/API thực tế. Trước khi coding adapter phải xác nhận chính xác API/NetSDK hỗ trợ loại event đã bật. Không giả định rằng callback realtime (`RealLoadPictureEx`) có thể tự trả lại event cũ.

Thứ tự ưu tiên khi Dashboard đọc dữ liệu:

1. Đọc cache/event store nội bộ cho ngày + camera + kênh đã chọn để render ngay.
2. Đồng bộ phần lịch sử còn thiếu từ NVR/camera theo khoảng thời gian cần xem.
3. Upsert metadata gốc vào event store bằng khóa ổn định của thiết bị/event, hoặc khóa suy ra từ `camera_id + channel + event_time + event_type + object_id`.
4. Cập nhật UI bằng dữ liệu đã hợp nhất; không cộng dồn mù quáng gây duplicate.
5. Duy trì listener realtime để thêm event mới sau mốc đồng bộ.

Mặc định Dashboard chỉ đồng bộ **hôm nay (00:00 đến hiện tại)**. Khi người dùng đổi ngày hoặc camera/kênh, chỉ truy vấn đúng khoảng đó. Không tải toàn bộ lịch sử NVR khi app khởi động.

## 4. Luồng chuẩn

```text
Camera/NVR (lịch sử AI event) ──► History sync adapter
                                           │ metadata thô
Camera/NVR (AI event mới) ───────► Realtime listener
                                           │
                                           ▼
Event store/cache (SQLite là ưu tiên) ─── event_id
        │
        ▼
Clip worker: chờ đủ hậu cảnh, tải DVR/NVR 10 giây
        │  5 giây trước event + 5 giây sau event
        ▼
Video analysis worker (Cosmos)
        │
        ▼
Suggestion store (JSON)
        │
        ▼
NLP/LLM worker
        │
        ▼
Thông báo / dashboard / truy vấn tự nhiên
```

## 5. Hợp đồng dữ liệu tối thiểu

### Event camera (`camera_event`)

```json
{
  "event_id": "cam01-ch00-20260831T101530-uuid",
  "camera_id": "cam01",
  "channel": 0,
  "event_time": "2026-08-31T10:15:30+07:00",
  "event_type": "person_detected",
  "event_action": "start",
  "camera_metadata": {},
  "source": "dahua_netsdk",
  "status": "synced"
}
```

`camera_metadata` phải lưu nguyên các trường mà SDK/camera trả về: object id, bounding box, số lượng, ảnh đính kèm, rule/channel và bất kỳ trường riêng của model camera. Thêm `source_event_id` nếu thiết bị trả về ID ổn định để đồng bộ lịch sử không bị trùng.

### Gợi ý từ video (`video_suggestion`)

```json
{
  "event_id": "...",
  "clip_path": "outputs/camera_clips/...mp4",
  "clip_start": "2026-08-31T10:15:25+07:00",
  "clip_end": "2026-08-31T10:15:35+07:00",
  "model": "Cosmos",
  "suggestion": {
    "summary": "...",
    "risk_level": "low",
    "recommended_action": "...",
    "evidence": []
  },
  "status": "ready"
}
```

## 6. Cách lấy clip 10 giây

- Khi event đến tại `T`, tạo job clip cho khoảng **`T - 5 giây` đến `T + 5 giây`**.
- Worker chờ đến sau `T + 5 giây`, rồi dùng `DownloadByTimeEx` của NetSDK tải đoạn ghi hình từ NVR/camera.
- File tải về có thể là `.dav`; chuyển sang `.mp4` trước khi phân tích.
- Nếu đầu ghi chưa có đủ 5 giây sau event hoặc tải lỗi: giữ job ở trạng thái `retry` và lưu lỗi, không tự bịa kết quả.
- Có chống trùng: các event cùng `camera_id`, `channel`, `event_type` trong cửa sổ ngắn chỉ tạo một clip/job.

## 7. Thành phần cần làm

| Thành phần | Trách nhiệm | Không làm |
|---|---|---|
| `camera_event_listener` | Đăng ký event AI NetSDK, chuẩn hóa và lưu metadata | Không gọi model video trực tiếp trong callback |
| `camera_history_sync` | Tải metadata lịch sử theo camera/kênh/khoảng thời gian và upsert | Không tải toàn bộ lịch sử khi mở app |
| `clip_worker` | Lấy/chuyển clip 10 giây, retry an toàn | Không đọc UI PyQt |
| `video_analysis_worker` | Gọi pipeline Cosmos cho clip, tạo JSON gợi ý | Không ghi đè metadata camera |
| `suggestion_store` | Lưu và tra theo `event_id` | Không để LLM sửa dữ liệu gốc |
| `nlp_worker` | Biến gợi ý thành ngôn ngữ tự nhiên/cảnh báo | Không tự khẳng định điều không có trong evidence |

## 8. Thứ tự triển khai

1. Xác nhận API/NetSDK để truy vấn **lịch sử metadata** của đúng loại event từ NVR/camera; ghi mẫu payload thật.
2. Tạo SQLite event store có index `camera_id, channel, event_time` và cơ chế upsert/chống trùng.
3. Khi app mở Dashboard: render cache trước, đồng bộ lịch sử hôm nay ở background, rồi refresh UI.
4. Tạo listener realtime chạy nền để upsert event mới sau mốc lịch sử đã đồng bộ.
5. Tạo hàng đợi/job và `clip_worker` tải được một clip 10 giây cho event cần phân tích.
6. Nối clip MP4 vào pipeline Cosmos hiện có; lưu `video_suggestion` theo `event_id`.
7. Viết adapter LLM nhận `camera_event + video_suggestion` và trả JSON/câu tiếng Việt.
8. Đưa dữ liệu vào Dashboard, sau đó mới mở rộng thông báo tự động.

## 9. Tiêu chí hoàn thành bản đầu

- Bật event AI trên camera và nhận được metadata thật vào event store.
- Khi mở app, Dashboard là màn hình đầu tiên và hiển thị cache ngay; lịch sử hôm nay được đồng bộ ở nền.
- Chọn ngày/camera/kênh khác chỉ tải đúng phạm vi đó, không nhân bản event khi đồng bộ lại.
- Một event tạo chính xác một clip 10 giây có thể mở được.
- Clip tạo một JSON gợi ý, liên kết đúng `event_id`.
- LLM tạo được văn bản tiếng Việt từ JSON đó và không cần xem lại video gốc.
- Khi camera, NVR hoặc model lỗi, job có trạng thái/lý do lỗi rõ ràng và không làm chết listener.

## 10. Các thông tin phải xác nhận trước khi viết adapter thật

- Model camera/đầu ghi, firmware và API/NetSDK truy vấn lịch sử event; event AI đã bật: người, xâm nhập, face detection hay loại nào khác.
- Camera lưu video ở đâu: camera trực tiếp hay NVR; kênh nào tương ứng.
- Thời lượng clip có phải luôn 5 giây trước + 5 giây sau không.
- LLM đích là API/model nào và đầu ra muốn là: cảnh báo, báo cáo, hay chatbot.
