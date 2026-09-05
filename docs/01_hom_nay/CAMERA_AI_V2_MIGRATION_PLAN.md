# Camera AI v2 — kế hoạch migration và giao diện chính

## Mục tiêu

Tạo Camera AI v2 trên repository `CameraDNCv2`, **giữ nguyên model/pipeline AI
đang chạy** và dùng trực tiếp source giao diện NVIDIA VSS đã clone. Giao diện
mặc định có ba cột:

1. **Camera & luồng phân tích:** live stream/clip, nhãn bất thường, timeline
   và sơ đồ trạng thái xử lý.
2. **Metadata Search:** tìm/lọc theo camera, kênh, thời gian, loại metadata,
   mức độ rủi ro và từ khóa.
3. **Camera AI Agent:** hỏi đáp, tóm tắt và giải thích event đang chọn.

Nguồn UI: `vendor/nvidia-video-search-and-summarization/`, Git submodule đến
`https://github.com/NVIDIA-AI-Blueprints/video-search-and-summarization.git`
tại commit `94e68f2`.

## Phạm vi giữ nguyên

| Thành phần hiện có | Vai trò trong v2 | Quyết định |
|---|---|---|
| `CameraAI/` | FastAPI, Dahua/NVR listener, SQLite, clip capture, WebSocket | Backend lõi |
| `audio_analysis_worker.py` | Speech/audio analysis | Giữ worker/model cũ |
| `video_analysis_worker.py` | Video anomaly analysis | Giữ worker/model cũ |
| `cosmos_code_base/` | Cosmos reasoning, search, summary | Worker phân tích sâu; không copy weights/cache |
| NVIDIA VSS UI | Source giao diện VSS/agent/search | Clone và cấu hình adapter, không dựng UI lại |

Không đưa lên Git: API key, credentials, NVR config thật, clips/videos,
database runtime, logs, virtual environments, model weights, Hugging Face/Torch
cache hay binary runtime.

## Kiến trúc đích

```text
Camera / NVR (Dahua, RTSP, metadata)
          |
          v
CameraAI FastAPI + NVR listener
          |-- event store / raw metadata
          |-- clip capture
          |-- audio/video workers cũ
          |-- Cosmos adapter (async)
          |-- REST + WebSocket
          v
NVIDIA VSS UI
 [Camera & flow] [Metadata search / timeline] [AI agent]
```

### Nguyên tắc dữ liệu

- Metadata NVR là **source of truth**; luôn giữ `raw_metadata` không bị model
  hay LLM sửa.
- Model chỉ bổ sung `labels`, `severity`, `confidence`, `summary`, model/version
  và trạng thái lỗi.
- `event_id` ổn định liên kết metadata, clip, worker, WebSocket và UI.
- Worker chạy queue/background; UI không chờ inference trong request chính.

## Cách dùng UI NVIDIA

- Không viết lại layout/component NVIDIA.
- Thay các endpoint VST/NIM bằng adapter CameraAI: không gọi
  `/v1/sensor/list`; lấy camera/event từ API CameraAI.
- Cột trái dùng stream/clip CameraAI và overlay `normal`, `review`,
  `abnormal`, `high`.
- Cột giữa dùng event metadata/timeline thật; chọn một event đồng bộ video và
  agent.
- Cột phải hiển thị agent với nguồn trả lời rõ ràng: NVR metadata, video model,
  audio model hoặc Cosmos. Khi service offline phải hiện trạng thái rõ ràng.

## Hợp đồng API v2

| API | Mục đích |
|---|---|
| `GET /api/events` | Search/lọc event metadata |
| `GET /api/events/{event_id}` | Raw metadata, labels, clip, AI result |
| `GET /clips/{clip_path}` | Evidence clip đã kiểm tra path |
| `POST /api/events/{event_id}/audio-analysis` | Queue audio worker cũ |
| `POST /api/events/{event_id}/video-analysis` | Queue video/Cosmos worker cũ |
| `POST /api/agent/query` | Agent trả lời theo event/filter context |
| `WS /ws` | Event mới và tiến trình worker |
| `GET /api/health` | DB, NVR, worker, Cosmos, storage |

## Lộ trình

### P0 — Repository sạch

- [x] Tạo `CameraDNCv2/` và push source nền tảng.
- [x] Đưa CameraAI và Cosmos source, bỏ runtime data/model/cache.
- [x] Bỏ API key hard-code và credential NVR mặc định.
- [x] Gắn clone source NVIDIA VSS qua Git submodule.
- [x] Thêm `.gitignore`, `.env.example`, README và tài liệu này.

### P1 — Giữ backend/model cũ

- [ ] Adapter audio, video và Cosmos; không thay weights/model.
- [ ] Chuẩn hóa event schema/migration SQLite không mất dữ liệu cũ.
- [ ] Health check, retry/timeout, structured log và smoke test
  metadata → event → clip → worker → WebSocket.

### P2 — Nối trực tiếp UI NVIDIA

- [ ] Dùng app NVIDIA VSS trong submodule làm frontend chính.
- [ ] Chuyển các calls VST/NIM sang CameraAI API.
- [ ] Nối video/clip, event selection, timeline và WebSocket.
- [ ] Nối Agent panel vào event/filter context và Cosmos khi sẵn sàng.

### P3 — Nhãn bất thường dựa metadata

- [ ] Mapping cấu hình được: metadata event type → label → default severity.
- [ ] AI được nâng/hạ severity nhưng luôn giữ label metadata gốc.
- [ ] Lưu audit trail: model/version, input, thời gian, confidence, lỗi.

### P4 — Kiểm thử/phát hành

- [ ] Test camera/NVR thật: reconnect, duplicate event, thiếu clip,
  worker/API offline.
- [ ] Test UI 1366px và 1920px.
- [ ] Viết hướng dẫn Windows/.env và clone submodule.

## Git strategy

1. `main`: release; `develop`: integration;
   `feature/cameraai-vss-adapter` và `feature/cosmos-adapter`: development.
2. UI NVIDIA luôn được giữ link upstream/attribution; thay đổi tích hợp CameraAI
   nằm ở lớp adapter của v2, không copy model NVIDIA.
3. Không force-push hoặc rewrite repo `CameraDNC` cũ.
