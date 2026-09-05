# Kế hoạch tích hợp AI phân tích âm thanh cho event metadata

## Mục tiêu

Tận dụng AI âm thanh đã có trong `cosmos_code_base/live_service.py` (`POST /transcribe`) để phân tích audio thật của clip 10 giây do `CameraAI` lấy từ NVR.

Không tạo thêm một model Whisper khác trong `CameraAI`. `CameraAI` là nơi quản lý event, clip, Dashboard và job; Cosmos là nơi xử lý audio-to-text.

## Luồng đích

```text
NVR gửi metadata SoundDetection / AudioAnomaly
        │
        ▼
CameraAI/dahua_client.py
  lưu event metadata gốc vào SQLite (status: pending)
        │
        ▼
Audio analysis worker chạy nền
  chờ đủ 5 giây sau event → tải clip thật 10 giây
        │
        ▼
ffprobe kiểm tra audio track
   ├── không có audio → status: no_audio
   └── có audio
           │
           ▼
ffmpeg → WAV 16 kHz, mono, PCM
           │
           ▼
POST Cosmos /transcribe
           │
           ▼
lưu transcript + chỉ số audio + trạng thái
           │
           ▼
LLM tạo gợi ý dựa trên metadata + transcript
           │
           ▼
Dashboard cập nhật event card / modal clip
```

## Nguyên tắc dữ liệu

- Metadata NVR là dữ liệu gốc, luôn được giữ nguyên.
- Transcript/gợi ý là dữ liệu suy luận bổ sung, không ghi đè metadata.
- Không có audio track hoặc không có lời nói là một kết quả hợp lệ, không phải lỗi hệ thống.
- Không kết luận “cãi vã”, “đập phá”, “đánh nhau” chỉ từ mức dB; cần transcript hoặc evidence video/audio rõ ràng.
- Mỗi event chỉ có tối đa một kết quả audio analysis hiện hành, liên kết bằng `event_id`.
- Production không tạo clip giả khi NVR/RTSP lỗi; clip giả chỉ dành cho `demo_mode=True`.

## Phạm vi file cần sửa/tạo

| File | Việc làm |
|---|---|
| `CameraAI/database.py` | Thêm bảng `audio_analyses` và các hàm tạo/cập nhật/lấy kết quả theo `event_id`. |
| `CameraAI/dahua_client.py` | Lưu event thật trước, enqueue job audio; không tải clip hay gọi AI ngay trong callback. |
| `CameraAI/audio_analysis_worker.py` *(mới)* | Worker nền: chờ hậu cảnh, lấy clip, kiểm tra/tách audio, gọi Cosmos, lưu kết quả. |
| `CameraAI/video_clipper.py` | Trả lỗi rõ ràng ở production; chỉ fallback synthetic clip khi `demo_mode=True`. |
| `CameraAI/main.py` | Khởi động/dừng worker, API trả event kèm audio analysis, broadcast event khi trạng thái đổi. |
| `CameraAI/static/js/app.js` | Render chip trạng thái audio và transcript/gợi ý trong modal event. |
| `CameraAI/templates/index.html` | Bổ sung vùng transcript, gợi ý AI và trạng thái audio trong modal clip. |
| `cosmos_code_base/live_service.py` | Không cần sửa ở bước đầu; dùng API `/transcribe` sẵn có. |

## Schema đề nghị

Tạo bảng `audio_analyses` thay vì thêm nhiều cột vào `events`:

```sql
CREATE TABLE audio_analyses (
    event_id INTEGER PRIMARY KEY,
    status TEXT NOT NULL,
    wav_path TEXT,
    transcript TEXT,
    segments_json TEXT,
    speech_detected INTEGER,
    audio_rms REAL,
    active_speech_seconds REAL,
    ignored_reason TEXT,
    audio_model TEXT,
    suggestion_json TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    analyzed_at TEXT,
    FOREIGN KEY(event_id) REFERENCES events(id)
);
```

Trạng thái chuẩn:

```text
pending → waiting_for_post_buffer → downloading_clip → extracting_audio
        → transcribing → completed

no_audio | failed
```

Không lưu WAV lâu dài trong production trừ khi có yêu cầu nghiệp vụ; clip MP4 và kết quả JSON là đủ để audit.

## Các bước triển khai

### Bước 1 — Làm sạch ranh giới demo và production

- [ ] `restart_listener_service()` chỉ khởi động `NVRDataSimulator` khi `config.DEMO_MODE=True`.
- [ ] Production không seed lịch sử giả từ `simulator.py`.
- [ ] `video_clipper.py` chỉ gọi `generate_synthetic_anomaly_clip()` trong demo mode.
- [ ] Nếu tải clip lỗi ở production: trả `None`/exception có thông tin lỗi, không ghi clip giả.

**Xong khi:** chạy với `demo_mode=False` không có event hoặc clip giả nào xuất hiện trong SQLite/Dashboard.

### Bước 2 — Thêm storage cho kết quả audio

- [ ] Thêm `audio_analyses` trong `database.init_db()`.
- [ ] Viết `create_audio_analysis(event_id)`, `update_audio_analysis(...)`, `get_audio_analysis(event_id)`.
- [ ] API `GET /api/events/{id}` trả thêm trường `audio_analysis`.
- [ ] Viết test nhỏ: tạo event → tạo analysis pending → update completed → đọc lại đúng dữ liệu.

**Xong khi:** restart app không mất kết quả transcript đã lưu.

### Bước 3 — Worker lấy clip và audio

- [ ] Tạo `audio_analysis_worker.py` dùng `queue.Queue` và một background thread.
- [ ] Callback chỉ enqueue `event_id` sau khi `database.save_event()` thành công.
- [ ] Worker lấy thời gian event từ DB, chờ đến `event_time + POST_BUFFER_SEC` nếu cần.
- [ ] Gọi `video_clipper.clip_event_video()` để lấy MP4 thật.
- [ ] Dùng `ffprobe` xác nhận có stream `audio`.
- [ ] Dùng FFmpeg xuất WAV `pcm_s16le`, 16 kHz, mono vào thư mục tạm.
- [ ] Luôn xóa WAV tạm sau khi gửi Cosmos.

**Xong khi:** một MP4 mẫu có audio tạo được WAV; MP4 không có audio cho trạng thái `no_audio`.

### Bước 4 — Gọi Cosmos transcription

- [ ] Thêm `COSMOS_AUDIO_URL` vào config/environment, mặc định `http://127.0.0.1:8765/transcribe`.
- [ ] Kiểm tra `GET /health` trước khi xử lý; nếu service chưa sẵn sàng lưu `failed`/retryable error.
- [ ] Gửi WAV với `Content-Type: application/octet-stream`.
- [ ] Gửi các header:

```text
X-Cosmos-Device-Id: <nvr identifier>
X-Cosmos-Channel: <channel>
X-Cosmos-Captured-At: <event time ISO-8601>
X-Cosmos-Audio-Source: event_clip
X-Cosmos-Audio-Sha256: <sha256 WAV>
```

- [ ] Lưu `text`, `speech_detected`, `audio_rms`, `active_speech_seconds`, `ignored_reason`, `audio_model` và latency từ response.
- [ ] Với `speech_detected=false`: đặt `completed`, transcript rỗng; không retry vô hạn.

**Xong khi:** clip tiếng Việt mẫu trả transcript và dữ liệu được lưu theo event tương ứng.

### Bước 5 — Tạo gợi ý ngôn ngữ tự nhiên *(đã xong về code)*

- [x] Chỉ gọi LLM sau khi transcription hoàn thành.
- [x] Prompt nhận metadata gốc + kết quả audio; yêu cầu JSON có `summary`, `risk_level`, `recommended_action`, `evidence`.
- [x] `evidence` phải nêu rõ nguồn: `NVR metadata`, `audio transcript`, hoặc `không có audio`.
- [x] Nếu transcript trống: gợi ý chỉ được nói về metadata do NVR báo, không bịa nội dung lời nói.
- [x] Lưu JSON vào `suggestion_json`.

**Xong khi:** event `SoundDetection` có gợi ý tiếng Việt, truy ngược được về metadata và transcript.

### Bước 6 — Hiển thị Dashboard *(đã xong về code)*

- [x] Event card hiện một trong các trạng thái: `Đang chờ clip`, `Đang phân tích âm thanh`, `Đã phân tích`, `Không có audio`, `Lỗi`.
- [x] Modal clip hiển thị metadata gốc, mức dB, transcript, gợi ý và lỗi (nếu có).
- [x] Khi worker cập nhật, broadcast WebSocket event mới để Dashboard refresh đúng card.
- [x] KPI/audio summary chỉ đếm metadata NVR; transcript chỉ bổ sung context, không làm tăng số event.

**Xong khi:** người dùng bấm một event và thấy đầy đủ clip 10 giây + kết quả audio theo cùng `event_id`.

## Cách test theo thứ tự

1. Test với file MP4 có tiếng nói tiếng Việt, chưa cần NVR thật.
2. Test MP4 không có audio → `no_audio`.
3. Test Cosmos không chạy → `failed` có thông báo dễ hiểu, listener không chết.
4. Test event metadata giả trong `demo_mode=True`.
5. Test NVR thật một kênh: metadata → clip thật → transcript.
6. Test hai event liên tiếp: listener vẫn nhận đủ, worker xử lý lần lượt.
7. Test restart app: event và kết quả cũ vẫn xem được từ SQLite.

## Không làm trong đợt đầu

- Không stream audio liên tục từ tất cả camera.
- Không chạy Whisper trong callback NetSDK/HTTP event listener.
- Không phân tích lại toàn bộ lịch sử event ngay khi mở app.
- Không tự tạo clip giả trong production.
- Không dùng transcript để thay thế metadata NVR.

## Phân tích hình ảnh của clip event *(đã tích hợp bản đầu)*

- [x] Thêm nút `Phân tích video` cạnh nút `Phân tích giọng nói` trong modal clip.
- [x] Tạo bảng `video_analyses`, lưu kết quả suy luận riêng theo `event_id`; không sửa metadata NVR gốc.
- [x] Tạo background worker lấy các frame đại diện tại giây 1, 5 và 9 của clip 10 giây.
- [x] Gọi tuần tự Cosmos `POST /analyze` với header `X-Cosmos-Analysis-Source: event_clip`.
- [x] Không để phân tích clip lịch sử tạo thêm replay event hoặc làm thay đổi bộ chống trùng của luồng live.
- [x] Tổng hợp mức rủi ro cao nhất và lấy số lượng lớn nhất của từng loại đối tượng qua các frame, không cộng trùng.
- [x] API `POST /api/events/{event_id}/video-analysis` enqueue job; API event trả thêm `video_analysis`.
- [x] Dashboard hiển thị trạng thái, tóm tắt, rủi ro, đối tượng, số frame và lỗi nếu có.

Cấu hình tùy chọn:

```text
COSMOS_VIDEO_URL=http://127.0.0.1:8765/analyze
VIDEO_ANALYSIS_SAMPLE_OFFSETS=1,5,9
```

Giới hạn có chủ đích: `/analyze` hiện phân tích từng JPEG độc lập. Kết quả nhiều frame cung cấp ảnh chụp tại nhiều mốc, nhưng không được xem là bằng chứng chắc chắn về chuyển động, hướng di chuyển, ý định hoặc diễn biến liên tục. Muốn kết luận theo thời gian phải bổ sung endpoint/model video-native ở giai đoạn sau.

## Tiêu chí hoàn thành

- Một metadata `AudioAnomaly` thật sinh ra đúng một job audio.
- Job tạo clip 10 giây thật hoặc có trạng thái lỗi/no-audio rõ ràng.
- Audio thật được Cosmos transcribe và lưu bền theo `event_id`.
- Dashboard hiện transcript/gợi ý, metadata gốc và evidence phân biệt rõ.
- Khi Cosmos/NVR lỗi, Dashboard vẫn hoạt động và listener không bị chặn.
