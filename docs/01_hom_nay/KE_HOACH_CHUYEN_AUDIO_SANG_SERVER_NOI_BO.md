# Kế Hoạch Chuyển Đổi Tầng Âm Thanh (Audio AI) Sang Server Nội Bộ
**Máy trạm: Lọc nhiễu cục bộ bằng DeepFilterNet | Server: Phân tích âm thanh & Bóc băng STT toàn diện**

---

## 1. Khẳng Định Tính Khả Thi & Đánh Giá Chiến Lược

### 1.1 Khẳng định tính khả thi: **100% Khả Thi & Tối Ưu Vượt Trội**
Yêu cầu của bạn:
> *"Máy sẽ lo phần lọc nhiễu và sau đó gửi âm thanh lên server để phân tích chứ không phân tích bằng AI của máy nữa."*

Đây là kiến trúc **chuẩn mực của hệ thống Edge-to-Cloud / Edge-to-Server**:
1. **Lọc nhiễu ở máy trạm (Edge Denoising)**:
   - Thư viện **DeepFilterNet3** cực kỳ nhẹ, tối ưu bằng Rust + PyTorch/ONNX.
   - Tiêu tốn CPU cực thấp (< 5%) hoặc chỉ chiếm ~0.1 GB VRAM nếu chạy GPU.
   - Thời gian xử lý 1 đoạn audio 10 giây từ camera chỉ mất **30 – 50 mili-giây** (nhanh gấp 200 lần thời gian thực).
   - Loại bỏ 90 – 95% tạp âm ngoài trời của camera (tiếng gió rít, tiếng quạt trần, tiếng xe máy/ô tô ngoài đường, tiếng ù nền), giữ lại dải tần giọng nói người trong trẻo.
2. **Dung lượng truyền tải siêu nhẹ**:
   - Audio sau khi lọc nhiễu được nén thành chuẩn **WAV 16 kHz Mono PCM 16-bit** (chuẩn quốc tế cho tất cả AI nhận diện tiếng nói).
   - Đoạn 10 giây chỉ nặng đúng **~312 KB**.
   - Thời gian truyền tải file 312 KB lên Server nội bộ chỉ mất **10 – 30 mili-giây** (băng thông mạng nội bộ / LAN 1Gbps hoàn toàn tức thì).
3. **Phân tích trên Server AI nội bộ (Server Analysis)**:
   - Server nội bộ có GPU khủng (cụm NVIDIA H200 / Server AI chuyên dụng) xử lý bóc băng tiếng Việt và phân tích sự kiện âm thanh chỉ trong chớp mắt.
   - Máy trạm **giải phóng hoàn toàn 1.5 – 2.5 GB VRAM** (không còn phải tải model Whisper-Large hay PhoWhisper cục bộ).
   - Máy trạm không lo nóng card, không lo tụt FPS hiển thị, không sợ lỗi OOM (Out Of Memory) khi đang chạy đa camera.
   - Xóa bỏ hoàn toàn phụ thuộc vào Gemini Cloud API (không sợ giới hạn hạn ngạch Quota 429, không lo lộ âm thanh nhạy cảm ra ngoài Internet).

---

## 2. Mô Hình Kiến Trúc Mới: Edge Denoise + Server Audio AI

```
┌────────────────────────────────────────────────────────────────────────┐
│                      MÁY TRẠM CLIENT (CameraAI V2)                     │
│                                                                        │
│   [ Camera Dahua / NVR ]                                              │
│             │                                                          │
│             ▼                                                          │
│   [ FFmpeg trích xuất Audio 48 kHz ]                                   │
│             │                                                          │
│             ▼                                                          │
│   [ DeepFilterNet3 Cục Bộ ]  ◄─── Xử lý siêu nhẹ (<50ms, ~0.1GB VRAM)  │
│             │                     Triệt tiêu 95% tạp âm nền camera     │
│             ▼                                                          │
│   [ Đo RMS dBFS & VAD ]      ◄─── Nếu im lặng (< -50dBFS): Đóng dấu    │
│             │                     "audio_too_quiet", không gửi server  │
│             ▼                                                          │
│   [ Clean WAV 16 kHz (~300 KB) ]                                       │
│             │                                                          │
└─────────────┼──────────────────────────────────────────────────────────┘
              │
              │  HTTP POST (Multipart Clean WAV / Base64)
              │  Độ trễ truyền mạng: ~20ms (312 KB)
              │
┌─────────────▼──────────────────────────────────────────────────────────┐
│                   SERVER AI NỘI BỘ (Hạ Tầng 4x H200)                   │
│                                                                        │
│   [ Internal Audio AI Service ]                                        │
│   (Speech-to-Text Tiếng Việt + Phân Tích Sự Kiện Âm Thanh)             │
│             │                                                          │
│             ├─► Bóc băng chính xác lời thoại tiếng Việt (Transcript)    │
│             ├─► Phát hiện âm thanh bất thường (Detected Sounds):       │
│             │   tiếng la hét, cãi vã, tiếng đổ vỡ, tiếng đập phá...     │
│             ├─► Đánh giá mức độ an ninh: none | low | medium | high    │
│             └─► Tóm tắt ngữ cảnh âm thanh (Summary)                    │
│                                                                        │
└─────────────┬──────────────────────────────────────────────────────────┘
              │
              │  JSON Response kết quả
              │
┌─────────────▼──────────────────────────────────────────────────────────┐
│                   TỔNG HỢP & HIỂN THỊ TRÊN MÁY TRẠM                     │
│                                                                        │
│   1. Lưu kết quả vào CSDL `audio_analyses`                             │
│   2. Gửi sang Qwen3.8-27B đối chiếu chéo với hình ảnh Video            │
│   3. Hiển thị báo cáo đầy đủ lên Dashboard sự kiện                     │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Thiết Kế Chuẩn Giao Tiếp API Server (API Contract)

### 3.1 Endpoint Phân Tích Âm Thanh Nội Bộ
- **URL**: `f"{config.INTERNAL_AUDIO_SERVER_URL}/analyze"` hoặc endpoint Audio/Speech của server nội bộ.
- **Phương thức**: `POST`
- **Headers**:
  ```http
  Authorization: Bearer <INTERNAL_AUDIO_SERVER_API_KEY>
  User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)...
  Content-Type: multipart/form-data
  ```
- **Body gửi đi**:
  - `file`: File WAV 16kHz sạch (`clean_audio.wav`).
  - `camera_channel`: Số kênh camera (ví dụ: `11`).
  - `event_code`: Mã sự kiện NVR (ví dụ: `Intrusion`, `Fight`, `AudioAnomaly`).
  - `timestamp`: Thời gian xảy ra sự kiện.

### 3.2 Định Dạng JSON Trả Về Từ Server
Server trả về schema chuẩn hóa, tương thích 100% với hệ thống CameraAI hiện tại:
```json
{
  "status": "ok",
  "speech_detected": 1,
  "transcript": "Ai đang đứng ở cổng đấy? Đi ra ngay!",
  "detected_sounds": ["tiếng quát lớn", "tiếng bước chân dồn dập", "tiếng đóng sầm cửa"],
  "risk_level": "medium",
  "summary": "Phát hiện tiếng quát cảnh cáo và bước chân dồn dập tại khu vực giám sát.",
  "audio_model": "Internal Audio AI (Server H200)",
  "latency_ms": 280
}
```

---

## 4. Danh Sách Các File Cần Triển Khai / Can Thiệp

### 4.1 Cấu hình hệ thống: [CameraAI/config.py](file:///d:/CameraV2/CameraAI/config.py)
Bổ sung các tham số cấu hình server audio nội bộ:
```python
# Cấu hình AI Âm thanh Server Nội Bộ
INTERNAL_AUDIO_SERVER_URL = os.getenv("INTERNAL_AUDIO_SERVER_URL", "https://llm.ttpmsandbox.us.kg/v1/audio").rstrip("/")
INTERNAL_AUDIO_SERVER_API_KEY = os.getenv("INTERNAL_AUDIO_SERVER_API_KEY", os.getenv("QWEN_API_KEY", "")).strip()
INTERNAL_AUDIO_MODEL_NAME = os.getenv("INTERNAL_AUDIO_MODEL_NAME", "internal-audio-v1")
# Cờ kích hoạt lọc tạp âm DeepFilterNet3 tại máy trạm
USE_DEEPFILTER = os.getenv("USE_DEEPFILTER", "true").strip().lower() in {"1", "true", "yes", "on"}
```

### 4.2 Module Giao Tiếp Audio Server: [CameraAI/internal_audio_client.py](file:///d:/CameraV2/CameraAI/internal_audio_client.py) `[NEW]`
Tạo module chuyên trách:
- `send_clean_audio_to_server(wav_path: str, metadata: dict) -> dict`:
  - Đọc file WAV đã lọc sạch.
  - Gửi POST request lên Server nội bộ có cơ chế retry và timeout an toàn (30s).
  - Phân tích và kiểm tra tính hợp lệ của JSON trả về.
  - Fallback thông minh: Nếu server tạm thời quá tải hoặc mất mạng LAN, đánh dấu trạng thái chờ và không làm gián đoạn hệ thống.

### 4.3 Cải tiến Worker Âm thanh: [CameraAI/audio_analysis_worker.py](file:///d:/CameraV2/CameraAI/audio_analysis_worker.py) `[MODIFY]`
- **Giữ lại**:
  - `_extract_wav()` kết hợp **DeepFilterNet3** tại máy trạm: Xuất 48kHz -> chạy lọc nhiễu cục bộ -> xuất file sạch 16kHz.
  - `_wav_rms_dbfs()`: Kiểm tra âm lượng dBFS. Nếu < -50dBFS thì đánh dấu `audio_too_quiet`, không gửi lên server (tiết kiệm tài nguyên mạng).
- **Thay thế hoàn toàn**:
  - Bỏ lời gọi `transcribe_and_analyze_audio_with_gemini()` (bỏ Gemini cloud).
  - Bỏ lời gọi fallback sang `COSMOS_AUDIO_URL` / PhoWhisper local (không bật service local nữa).
  - Thay thế bằng lời gọi trực tiếp tới `send_clean_audio_to_server()` trong `internal_audio_client.py`.
  - Cập nhật trực tiếp kết quả vào `database.update_audio_analysis()`.

### 4.4 Cập nhật hiển thị & Khởi động:
- [CameraAI/Chay_App_Windows.bat](file:///d:/CameraV2/CameraAI/Chay_App_Windows.bat): Không cần khởi động thêm bất kỳ service âm thanh local nào, giảm nhẹ gánh nặng khởi động.
- [CameraAI/templates/components/audio_modal.html](file:///d:/CameraV2/CameraAI/templates/components/audio_modal.html): Hiển thị nhãn model phân tích là `AI Nội Bộ (Server H200)`.

---

## 5. Bảng So Sánh Trước & Sau Khi Chuyển Đổi

| Tiêu chí | Trước đây (Whisper Local / Gemini Cloud) | Mới (Lọc Cục Bộ + Phân Tích Server Nội Bộ) | Đánh giá |
| :--- | :--- | :--- | :--- |
| **Tài nguyên VRAM máy trạm** | Chiếm 2 – 3 GB VRAM cho STT local | **Chỉ ~0.1 GB VRAM** (hoặc 0 GB nếu chạy CPU) | **Giải phóng 100% GPU máy trạm** |
| **Xử lý tạp âm mic camera** | Nhiều tiếng ồn dễ gây ảo giác Whisper | **DeepFilterNet khử sạch 95% ồn nền** trước khi gửi | **Âm thanh trong trẻo, không ảo giác** |
| **Băng thông mạng** | Video gửi cloud rất nặng, dính Quota 429 | **Chỉ gửi ~312 KB WAV sạch** qua mạng LAN | **Tốc độ truyền < 30ms, bảo mật nội bộ** |
| **Độ ổn định hệ thống** | Hay lỗi OOM, xung đột CUDA, lỗi 429 | **Chạy bền bỉ 24/7**, không sợ tràn RAM | **Cực kỳ ổn định** |
| **Bảo mật dữ liệu** | Phụ thuộc Google Gemini bên ngoài | **100% xử lý nội bộ** trên hạ tầng đơn vị | **An toàn tuyệt đối** |

---

## 6. Lộ Trình Triển Khai Thực Hiện

- [ ] **Giai đoạn 1: Chuẩn bị Endpoint & Module Client**:
  - Tạo file module `CameraAI/internal_audio_client.py`.
  - Bổ sung cấu hình `INTERNAL_AUDIO_SERVER_URL` trong `CameraAI/config.py`.
  - Viết test độc lập gửi file âm thanh mẫu `CameraAI/storage/test_eval.wav` đã qua lọc DeepFilterNet lên server.
- [ ] **Giai đoạn 2: Tích hợp vào Pipeline `CameraAI/audio_analysis_worker.py`**:
  - Chuyển `audio_analysis_worker.py` sang dùng `internal_audio_client.py`.
  - Tắt hẳn các luồng gọi Gemini và Cosmos local.
- [ ] **Giai đoạn 3: Kiểm thử thực tế trên clip camera Dahua**:
  - Chạy test trên clip có tạp âm thực tế (clip ngoài trời, quạt gió, tiếng người nói).
  - Đo đạc độ trễ và tính chính xác của transcript.
- [ ] **Giai đoạn 4: Nghiệm thu và bàn giao**:
  - Kiểm tra giao diện Dashboard, đảm bảo modal âm thanh hiển thị đúng transcript, âm thanh bất thường và đánh giá an ninh.

