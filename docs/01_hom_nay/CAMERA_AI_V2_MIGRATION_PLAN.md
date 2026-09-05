# Camera AI v2 — kế hoạch migration và giao diện chính

## Mục tiêu

Chuyển source an toàn sang `CameraDNCv2`, giữ nguyên model/pipeline hiện có,
và xây giao diện mặc định theo bố cục ba cột của demo NVIDIA:

1. Camera & luồng phân tích: live stream/clip, labels, timeline và trạng thái.
2. Metadata Search: lọc theo camera, kênh, thời gian, event type, severity.
3. Camera AI Agent: tóm tắt, hỏi đáp và giải thích event đang chọn.

## Thành phần được giữ

| Nguồn | Vai trò v2 |
|---|---|
| `CameraAI/` | FastAPI, Dahua/NVR listener, SQLite, clip capture, WebSocket |
| `audio_analysis_worker.py` | Audio/speech analysis cũ |
| `video_analysis_worker.py` | Video anomaly analysis cũ |
| `cosmos_code_base/` | Cosmos reasoning, search và summary cũ |

Không đưa vào Git: credentials, NVR config, API keys, clips/video, SQLite
runtime, logs, virtual environments, model weights và Hugging Face/Torch cache.

## Kiến trúc đích

```text
Camera/NVR -> CameraAI FastAPI -> event store + clip + old workers
                                    |              |
                                    +-- REST/WS ---+-> Web UI
Web UI: [Camera & flow] [Metadata search/timeline] [AI agent]
```

- Metadata NVR là nguồn gốc, được lưu cùng `raw_metadata` và không bị AI sửa.
- AI chỉ thêm label, severity, confidence, model/version, summary và lỗi.
- Mỗi event dùng `event_id` ổn định để liên kết clip, workers và UI.
- Worker chạy async; UI không chờ inference trong HTTP request.

## Hợp đồng API v2

| API | Mục đích |
|---|---|
| `GET /api/events` | Search/lọc metadata event |
| `GET /api/events/{event_id}` | Raw metadata, labels, clip, AI result |
| `GET /clips/{clip_path}` | Clip evidence đã kiểm tra path |
| `POST /api/events/{event_id}/audio-analysis` | Queue audio worker cũ |
| `POST /api/events/{event_id}/video-analysis` | Queue video/Cosmos worker cũ |
| `POST /api/agent/query` | Hỏi đáp theo event/filter context |
| `WS /ws` | Event mới và tiến trình worker |
| `GET /api/health` | DB, NVR, worker, Cosmos, storage |

## Roadmap

### P0 — Repository sạch

- [x] Tạo repo staging riêng `CameraDNCv2/`.
- [x] Đưa source CameraAI và Cosmos, bỏ runtime data/model/cache.
- [x] Bỏ API key hard-code và NVR credential mặc định khỏi source.
- [x] Thêm `.env.example`, `.gitignore`, README và plan.
- [x] Gắn clone source NVIDIA VSS qua Git submodule, cố định upstream commit.
- [x] Commit nền tảng sạch đã được chuẩn bị sau khi kiểm tra không còn secret.

### P1 — Giữ backend/model cũ, chuẩn hóa integration

- [ ] Adapter audio, video và Cosmos worker; không thay weights/model.
- [ ] Event schema/migration không làm mất dữ liệu SQLite cũ.
- [ ] Health, retry, timeout, structured log và smoke test event-to-WebSocket.

### P2 — Dùng trực tiếp giao diện NVIDIA làm trang chính

- [x] Clone source tại `vendor/nvidia-video-search-and-summarization/`, không viết lại UI từ đầu.
- [ ] Cấu hình UI NVIDIA dùng API CameraAI thay cho VST/NIM endpoint.
- [ ] Nối cột trái với stream/clip CameraAI, cột giữa với event metadata, cột phải với agent hiện có.

### P3 — Nhãn bất thường từ metadata

- [ ] Mapping cấu hình được: event type -> label -> default severity.
- [ ] AI được nâng/hạ severity nhưng metadata label gốc luôn được giữ.
- [ ] Lưu audit trail: model/version, input, thời gian, confidence, lỗi.

### P4/P5 — Tích hợp và phát hành

- [ ] Cosmos nhận event JSON + clip path, không copy weights/cache.
- [ ] Test camera thật: reconnect, duplicate event, thiếu clip, worker/API offline.
- [ ] Test UI 1366px và 1920px; viết hướng dẫn Windows/.env.

## Git strategy

- `main`: release; `develop`: integration; các branch `feature/ui-vision-search`
  và `feature/cosmos-adapter`.
- Commit nền tảng trước, API/contracts tiếp theo, UI tĩnh sau đó mới WebSocket.
- Không force-push hoặc rewrite repository `CameraDNC` cũ.
