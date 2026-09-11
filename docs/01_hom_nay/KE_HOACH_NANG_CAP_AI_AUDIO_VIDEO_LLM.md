# Kế Hoạch Nâng Cấp Hệ Thống AI Đa Tầng (CameraAI V2)
**Audio (DeepFilterNet + Whisper Large-v3) | Video (Cosmos-Reason2-8B Quantized) | LLM (Qwen3.8-27B)**

---

## 1. Bối Cảnh & Mục Tiêu

Hệ thống **CameraAI V2** nâng cấp từ kiến trúc đơn lẻ sang mô hình **Phân tích Đa Tầng (Multi-tier AI Pipeline)**:
1. **Tầng Âm thanh (Audio AI)**: Lọc sạch tạp âm môi trường camera bằng **DeepFilterNet**, sau đó nhận diện giọng nói tiếng Việt bằng **Whisper Large-v3**.
2. **Tầng Thị giác (Vision AI)**: Nâng cấp mô hình suy luận ngữ cảnh hành vi sang **Cosmos-Reason2-8B**, áp dụng **Quantization (4-bit AWQ hoặc FP8)** để chạy mượt mà trên phần cứng cục bộ.
3. **Tầng Đánh giá & Báo cáo (Synthesis LLM)**: Sử dụng **Qwen3.8-27B** làm bộ não tổng hợp cuối cùng (nhận evidence từ NVR, Audio và Video để kết luận sự việc và đưa khuyến nghị cho nhân viên vận hành). File cấu hình chi tiết của Qwen sẽ được đưa vào sau khi hoàn thành 2 mô hình Audio và Video.

---

## 2. Phân Bổ Tài Nguyên & Khả Thi Phần Cứng

### Thông số máy chủ hiện tại:
- **GPU**: NVIDIA GeForce RTX 5070 Ti (Kiến trúc Blackwell, 16.303 MB VRAM ~ 16GB).
- **CUDA Version**: 13.2 (Hỗ trợ Tensor Cores thế hệ mới, Native FP8 và INT4).
- **Hệ điều hành**: Windows 11 64-bit, Python 3.11.

### Bảng tính toán VRAM khi chạy đồng thời:

| Hạng mục | Thành phần | Trọng số / Kiểu dữ liệu | VRAM chiếm dụng | Ghi chú |
| :--- | :--- | :--- | :--- | :--- |
| **Hệ điều hành & Desktop** | Windows DWM, Display, App | - | ~0.8 – 1.0 GB | Mức nền khi bật máy |
| **Audio AI: Lọc nhiễu** | DeepFilterNet3 | PyTorch / ONNX (48 kHz) | ~0.1 – 0.2 GB (hoặc CPU) | Xử lý 10s audio < 50ms |
| **Audio AI: Nhận diện giọng nói** | Whisper Large-v3 | CTranslate2 INT8 / FP16 | ~1.5 – 2.2 GB | Dùng `faster-whisper` để tối ưu VRAM |
| **Video AI: Suy luận thị giác** | Cosmos-Reason2-8B | AWQ 4-bit hoặc FP8 | ~5.5 – 8.0 GB | Giảm từ 16GB (BF16) xuống còn ~6GB |
| **KV-Cache & Context Buffer** | vLLM / Model Runner | PagedAttention | ~1.5 – 2.0 GB | Đủ cho chuỗi frame clip 10 giây |
| **TỔNG DỰ KIẾN (Audio + Video)** | **Chạy cục bộ trên RTX 5070 Ti** | - | **~9.4 – 13.4 GB** | **An toàn tuyệt đối trong ngưỡng 16GB VRAM** |
| **LLM: Tổng hợp** | Qwen3.8-27B | Cấu hình riêng (API / Quant) | Nhận file cấu hình sau | Tách độc lập, không tranh chấp VRAM runtime |

---

## 3. Thiết Kế Chi Tiết & Phương Pháp Kỹ Thuật

```
[ Camera Dahua NVR ]
        │
        ├─ Video Stream / Clip (10s) ──► FFmpeg tách Video Frames (0.4 - 1 FPS)
        │                                        │
        │                                        ▼
        │                               ┌─────────────────────────────┐
        │                               │  Cosmos-Reason2-8B (vLLM)   │
        │                               │   Quantized (AWQ 4-bit/FP8) │
        │                               └──────────────┬──────────────┘
        │                                              │ Video Evidence
        │                                              ▼
        └─ Audio Stream / WAV ─────────► [ DeepFilterNet3 ] (Lọc tạp âm)
                                                       │ Audio sạch
                                                       ▼
                                        [ Whisper Large-v3 ] (STT)
                                                       │ Transcript tiếng Việt
                                                       ▼
                                      ┌─────────────────────────────────┐
                                      │   Synthesis Engine (LLM)        │
                                      │        Qwen3.8-27B              │
                                      │ (NVR Meta + Video + Audio Ev.)  │
                                      └────────────────┬────────────────┘
                                                       │
                                                       ▼
                                      [ Báo cáo sự kiện & Cảnh báo UI ]
```

---

### Module 1: AI Âm Thanh (Audio Pipeline)

#### Thách thức thực tế:
- Mic thu âm camera thường đặt ngoài trời hoặc trần nhà: nhiều tiếng gió, xe cộ, quạt thông gió, tạp âm nền khiến Whisper dễ bị "ảo giác" (hallucination) hoặc bỏ sót tiếng người nói thì thầm/xa.

#### Giải pháp kỹ thuật:
1. **Khử tạp âm bằng DeepFilterNet3**:
   - Sử dụng thư viện `deepfilternet`.
   - FFmpeg xuất WAV ở tần số lấy mẫu chuẩn **48 kHz** (chuẩn của DeepFilterNet3).
   - DeepFilterNet lọc sạch 90-95% tiếng ồn xung quanh, chỉ giữ lại phổ giọng nói rõ ràng.
   - Resample về **16 kHz** chuẩn cho Whisper.
2. **Nhận diện giọng nói bằng Whisper Large-v3**:
   - Engine: Khuyến nghị **`faster-whisper` (CTranslate2)** hoặc **`whisper-large-v3-turbo`**.
   - Ưu điểm của `faster-whisper`:
     - Tốc độ nhanh gấp 4 lần `openai/whisper` gốc.
     - Tiêu tốn VRAM chỉ ~1.5 GB (ở chế độ `int8_float16`).
     - Có sẵn VAD (Voice Activity Detection - Silero VAD) để bỏ qua các đoạn im lặng hoặc không có người nói.
3. **Các file cần can thiệp**:
   - `CameraAI/audio_analysis_worker.py`: Bổ sung bước tiền xử lý lọc DeepFilterNet trước khi đưa vào STT.
   - `cosmos_code_base/live_service.py`: Cập nhật endpoint `/transcribe` hỗ trợ DeepFilterNet + Whisper Large-v3.
   - `cosmos_code_base/audio_to_text.py`: Bổ sung module chuyển đổi dùng DeepFilterNet.

---

### Module 2: AI Hình Ảnh / Video (Cosmos-Reason2-8B + Quantization)

#### Thách thức thực tế:
- `nvidia/Cosmos-Reason2-8B` nguyên bản ở định dạng BF16 chiếm ~16GB dung lượng bộ nhớ. Nếu tải toàn bộ trọng số gốc lên GPU RTX 5070 Ti 16GB sẽ gây tràn bộ nhớ (Out-Of-Memory / OOM) ngay khi nạp frame hoặc khởi động worker audio.

#### Giải pháp kỹ thuật:
1. **Lựa chọn định dạng nén (Quantization)**:
   - **Lựa chọn A (Tối ưu nhất cho vLLM)**: **AWQ 4-bit** (`Cosmos-Reason2-8B-AWQ` hoặc tự quantize bằng AutoAWQ). VRAM chiếm ~5.5GB, suy luận cực nhanh trên Tensor Cores.
   - **Lựa chọn B (Chất lượng cao nhất)**: **FP8 (Float8)**. RTX 5070 Ti hỗ trợ FP8 phần cứng native, giữ 99% độ chính xác gốc, VRAM chiếm ~8.5GB.
   - **Lựa chọn C (Dự phòng cho HuggingFace Transformers)**: `bitsandbytes` (NF4 / 4-bit) với `load_in_4bit=True`.
2. **Cấu hình vLLM Runtime**:
   - Tham số `--gpu-memory-utilization`: Đặt mức `0.55` – `0.60` (để dành 40% VRAM cho Audio và OS).
   - `max_model_len`: Giới hạn hợp lý (ví dụ: 16.384 hoặc 32.768 tokens) phù hợp với chuỗi frame ngắn 5-10s của camera.
3. **Các file cần can thiệp**:
   - `cosmos_code_base/src/performance.py`: Thêm profile mới `rtx5070ti_cosmos8b_quant`.
   - `cosmos_code_base/live_service.py`: Cập nhật cấu hình load model `--model-id` và cờ `--quantization`.
   - `CameraAI/video_analysis_worker.py`: Đảm bảo định dạng prompt và kết quả trả về từ bản 8B tương thích hoàn toàn với schema sự kiện hiện có.

---

### Module 3: Tầng LLM Tổng Hợp (Qwen3.8-27B)

#### Thách thức & Cách tiếp cận:
- Bản thân model Qwen 27B cục bộ cần từ 16GB – 20GB VRAM (ngay cả khi quantize 4-bit). Do đó, tầng LLM này được quy hoạch ở dạng linh hoạt:
  - Có thể chạy trên server phụ chuyên dụng, local instance với GPU thứ hai, hoặc qua endpoint suy luận vLLM / Ollama / OpenAI-compatible API.
- **Tiến độ**: Theo thống nhất, **file cấu hình chi tiết của Qwen3.8-27B sẽ được gửi sau** khi hoàn tất và ổn định 2 AI Video và Audio.
- **Chuẩn bị sẵn trong code**:
  - `CameraAI/gemini_video_report.py` và `CameraAI/audio_analysis_worker.py` sẽ được module hóa thành `LLMSummaryAdapter` chuẩn OpenAI API (chỉ cần đổi `base_url`, `model_name`, `api_key` là kích hoạt ngay Qwen3.8-27B).

---

## 4. Lộ Trình Triển Khai Chi Tiết (Roadmap)

### Giai đoạn 1: Hoàn thiện AI Âm thanh (Audio: DeepFilterNet + Whisper Large-v3)
- [x] **Bước 1.1**: Cài đặt và kiểm tra môi trường:
  - Cài `deepfilternet` và `faster-whisper` (hỗ trợ CUDA RTX 5070 Ti).
  - Viết script test độc lập: nạp 1 file audio mẫu -> lọc qua DeepFilterNet -> đưa vào Whisper Large-v3 -> đo đạc chất lượng văn bản và thời gian xử lý (đã test thực tế, độ trễ chỉ ~220ms cho clip 10s).
- [x] **Bước 1.2**: Tích hợp vào codebase CameraV2:
  - Cập nhật module `cosmos_code_base/audio_enhancer.py` làm cầu nối tích hợp.
  - Cập nhật hàm xử lý âm thanh trong `cosmos_code_base/live_service.py` (`/transcribe`).
  - Thêm cấu hình biến môi trường: `COSMOS_AUDIO_MODEL=whisper-large-v3-turbo`, `USE_DEEPFILTER=true`.
  - Cập nhật `CameraAI/audio_analysis_worker.py` và `cosmos_code_base/audio_to_text.py` để tương thích kết quả mới.
- [x] **Bước 1.3**: Kiểm thử thực tế trên clip camera Dahua:
  - Test các tình huống: clip không có tiếng, clip ồn nền, clip có hội thoại trên kho video Dahua thực tế tại `CameraAI/storage/clips`.


### Giai đoạn 2: Nâng cấp AI Video (Cosmos-Reason2-8B + Quantization)
- [ ] **Bước 2.1**: Xác định checkpoint và phương pháp Quantization cho Cosmos-Reason2-8B:
  - Kiểm tra tương thích vLLM với checkpoint Cosmos 8B FP8 / AWQ.
  - Tinh chỉnh `gpu_memory_utilization` để không xung đột VRAM với Whisper.
- [ ] **Bước 2.2**: Cập nhật runtime code:
  - Cấu hình lại `cosmos_code_base/src/performance.py` và `live_service.py`.
  - Kiểm tra tốc độ suy luận (latency per sequence 5-10s) trên RTX 5070 Tcòn 
- [ ] **Bước 2.3**: Kiểm thử video thực tế:
  - Test nhận diện hành vi (đột nhập, đánh nhau, phương tiện, người lạ) với model 8B.

### Giai đoạn 3: Tích hợp LLM Qwen3.8-27B & Bàn giao toàn diện
- [ ] **Bước 3.1**: Tiếp nhận file cấu hình Qwen3.8-27B từ người dùng.
- [ ] **Bước 3.2**: Tích hợp adapter kết nối Qwen vào hệ thống tạo báo cáo cuối cùng.
- [ ] **Bước 3.3**: Chạy kiểm thử End-to-End: Clip Dahua -> Bóc tách Frame & Audio -> Cosmos 8B + DeepFilterNet Whisper -> Qwen tổng hợp -> Hiển thị Dashboard hoàn chỉnh.

---

## 5. Tiêu Chuẩn Nghiệm Thu (Acceptance Criteria)

1. **Hiệu năng & VRAM**:
   - Cả 2 service Audio và Video chạy đồng thời không vượt quá **14GB VRAM** trên RTX 5070 Ti (đảm bảo độ ổn định 24/7, không OOM).
2. **Chất lượng âm thanh**:
   - Tạp âm nền được triệt tiêu rõ rệt sau khi qua DeepFilterNet.
   - Transcript tiếng Việt của Whisper Large-v3 không bị lặp từ (repetition) hoặc ảo giác khi gặp đoạn im lặng.
3. **Độ chính xác video**:
   - Cosmos-Reason2-8B mô tả chính xác bối cảnh và đối tượng trong clip mà không bị suy đoán vô căn cứ.
4. **Độ trễ (Latency)**:
   - Một clip sự kiện 10 giây: xử lý âm thanh < 2 giây, xử lý video < 4 giây, tổng thời gian có kết quả báo cáo < 7-8 giây.

