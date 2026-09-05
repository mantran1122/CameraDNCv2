# Chuyển tiếng nói camera live thành văn bản

Luồng này chạy song song với Cosmos hình ảnh:

```text
NetSDK live stream -> đoạn DAV tạm -> FFmpeg (WAV 16 kHz) -> POST /transcribe -> PhoWhisper -> cột TIẾNG NÓI
```

## Điều kiện

- Camera/đầu ghi phải bật audio cho kênh đang xem và phía vận hành phải cho phép xử lý audio.
- Máy chạy `NetSDK_Camera` cần có `ffmpeg` trong `PATH`.
- `live_service.py` cần chạy ở máy GPU, có `transformers` và quyền tải model
  tiếng Việt `vinai/PhoWhisper-small` lần đầu.

## Chạy service

```bash
export COSMOS_LIVE_PROMPT_PROFILE=admissions
export COSMOS_AUDIO_LANGUAGE=vi
# Bỏ nhiễu nền/yên lặng trước khi gửi sang PhoWhisper.
export COSMOS_AUDIO_MIN_RMS=0.01
export COSMOS_AUDIO_MODEL=vinai/PhoWhisper-small
export COSMOS_AUDIO_BEAM_SIZE=5
# Chỉ hiển thị transcript khi beam search và greedy decode cùng xác nhận.
export COSMOS_AUDIO_REQUIRE_DECODER_AGREEMENT=true
python live_service.py --host 0.0.0.0 --port 8770 --gpu-memory-utilization 0.45
```

PhoWhisper và beam search 5 là mặc định. Nếu bản `small` đã chạy ổn nhưng phòng quá xa/ồn
và GPU còn đủ bộ nhớ, có thể thử chất lượng cao hơn bằng
`export COSMOS_AUDIO_MODEL=vinai/PhoWhisper-medium`, rồi khởi động lại service.

## Chạy app camera trên Windows

```powershell
$env:COSMOS_LIVE_URL = "http://127.0.0.1:8770/analyze"
$env:COSMOS_SAMPLE_INTERVAL_SECONDS = "10"
$env:COSMOS_AUDIO_INTERVAL_SECONDS = "15"
$env:COSMOS_AUDIO_CHUNK_SECONDS = "10"
python .\launcher.py
```

## Xác minh audio có đúng từ camera

Mặc định `COSMOS_AUDIO_SOURCE=sdk`: client ghi từ chính `playID` của kênh đang
xem, không lấy microphone máy tính. Để lưu tối đa 10 WAV gần nhất và tự nghe đối
chiếu trước khi mở app:

```powershell
$env:COSMOS_AUDIO_SOURCE = "sdk"
$env:COSMOS_AUDIO_DEBUG_DIR = "D:\dnc\audio_debug"
$env:COSMOS_AUDIO_DEBUG_MAX_FILES = "10"
```

Mỗi transcript hợp lệ hiển thị nguồn, kênh, RMS, thời lượng có giọng và 12 ký tự
đầu của SHA-256. Tên WAV kiểm tra chứa cùng SHA, chứng minh file nghe thủ công là
đúng bytes đã gửi cho `/transcribe`. Debug WAV chứa âm thanh nhạy cảm; tắt bằng
`Remove-Item Env:COSMOS_AUDIO_DEBUG_DIR` sau khi kiểm tra xong.

Trong **Xem camera trực tiếp**, bật cả hai ô: **Phân tích Cosmos** và
**Chuyển tiếng nói thành văn bản**.

Nút biểu tượng loa dưới khung video bật/tắt âm thanh nghe trực tiếp qua NetSDK.
Nút này độc lập với ô chuyển lời nói thành văn bản.

Service dùng VAD theo từng frame để bỏ qua im lặng/nhiễu đều, không cho Whisper
kế thừa câu từ chunk trước, chặn transcript lặp giữa các chunk và các mẫu
hallucination phổ biến như lời mời đăng ký kênh. Mặc định
`COSMOS_AUDIO_MIN_RMS=0.01` ưu tiên không ghi nhầm tiếng nền; tăng lên `0.02` nếu
vẫn có nội dung bịa. Giá trị nhỏ hơn `0.005` sẽ tự được giới hạn ở `0.005` để
tránh đưa gần-im-lặng vào model. Giảm nhẹ chỉ khi đã nghe WAV đối chiếu và xác
nhận giọng nói thật bị bỏ qua.

Để tránh hiện một câu model tự bịa khi audio mờ hoặc có nhạc, service mặc định
chạy thêm một lần decode xác nhận. Nếu hai kết quả khác nhiều, response trả
`text` rỗng và `ignored_reason=decoder_disagreement`; service không thay bằng
một câu khác. Cách này tăng gần gấp đôi thời gian GPU cho những đoạn có lời nói,
nhưng ưu tiên độ tin cậy. Chỉ tắt khi cần tốc độ bằng
`COSMOS_AUDIO_REQUIRE_DECODER_AGREEMENT=false`.

Mặc định app ghi một đoạn ngắn trực tiếp từ `playID` NetSDK đang mở. Vì vậy
không cần public/NAT cổng RTSP 554. Đoạn DAV tạm được xóa ngay sau khi FFmpeg
tách audio.

Chỉ khi chủ động đặt `$env:COSMOS_AUDIO_SOURCE = "rtsp"`, app mới dùng RTSP Dahua:

```text
rtsp://<user>:<password>@<host>:554/cam/realmonitor?channel=<1-based>&subtype=<0-or-1>
```

Nếu đầu ghi dùng RTSP URL khác, đặt template này trước khi mở app. Các biến
`{host}`, `{username}`, `{password}`, `{channel}`, `{subtype}` sẽ được thay tự động:

```powershell
$env:COSMOS_AUDIO_RTSP_URL = "rtsp://{username}:{password}@{host}:554/cam/realmonitor?channel={channel}&subtype={subtype}"
```

Nếu đầu ghi không mở RTSP ở cổng 554, đặt cổng thật trước khi mở app:

```powershell
$env:COSMOS_AUDIO_RTSP_PORT = "554"
$env:COSMOS_AUDIO_CONNECT_TIMEOUT_SECONDS = "8"
```

Lỗi `RTSP quá thời gian kết nối` nghĩa là Windows không truy cập được cổng
RTSP của đầu ghi, không phải lỗi Whisper. Kiểm tra nhanh bằng
`Test-NetConnection <IP> -Port <RTSP_PORT>`.

NetSDK tạo một đoạn DAV tạm trong thư mục temp của Windows để lấy cả audio từ
kết nối SDK; client xóa đoạn này ngay sau khi FFmpeg xử lý. WAV được gửi trong
bộ nhớ và service xóa file WAV tạm ngay sau khi Whisper hoàn tất.
