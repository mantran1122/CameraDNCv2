# Hướng Dẫn Chạy Dự Án Cosmos Video Analyzer

Tài liệu này gom các phần cần thiết để cài môi trường, chạy phân tích, mở giao diện web và hiểu luồng xử lý của ứng dụng.

## 1. Yêu cầu môi trường

- Windows 10/11.
- Python 3.11 đã cài và gọi được bằng lệnh `py -3.11`.
- GPU NVIDIA đủ VRAM để chạy model `nvidia/Cosmos-Reason2-2B`.
- Driver NVIDIA/CUDA phù hợp với PyTorch CUDA 13.0 hoặc CUDA 12.8.
- `ffmpeg` và `ffprobe` có trong `PATH`.
- Dung lượng đĩa còn trống vì model, cache và chunk video sẽ nằm trong `local_env/` và `outputs/`.

Kiểm tra nhanh:

```bat
py -3.11 --version
ffmpeg -version
ffprobe -version
```

## 2. Cài đặt package

Chạy script cài đặt có sẵn:

```bat
install_D.bat
```

Script này sẽ:

- Tạo virtual environment tại `local_env\.venv`.
- Tạo các thư mục cache local: `local_env\pip_cache`, `local_env\hf_cache`, `local_env\torch_cache`.
- Cài PyTorch CUDA 13.0, nếu lỗi sẽ thử CUDA 12.8.
- Cài các dependency trong `requirements.txt`.
- In thông tin GPU để xác nhận CUDA đã hoạt động.

Nếu muốn cài thủ công:

```bat
py -3.11 -m venv local_env\.venv
call local_env\.venv\Scripts\activate
python -m pip install --upgrade pip setuptools wheel
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu130
pip install --upgrade -r requirements.txt
```

Nếu CUDA 13.0 không phù hợp:

```bat
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
```

## 3. Chuẩn bị video

Đặt video demo tại:

```text
static/demo.mp4
```

Hoặc mở UI Streamlit và upload file MP4 mới. Khi upload video mới, app sẽ ghi đè `static/demo.mp4` và xóa `outputs/result_demo.json` cũ.

## 4. Chạy phân tích bằng CLI

Chạy script:

```bat
run_analyze.bat
```

Lệnh tương đương:

```bat
call local_env\.venv\Scripts\activate
python main.py ^
  --video static/demo.mp4 ^
  --model nvidia/Cosmos-Reason2-2B ^
  --hardware-profile rtx5070ti_16gb ^
  --output outputs/result_demo.json ^
  --chunks-dir outputs/chunks ^
  --vector-db outputs/lancedb
```

Profile có sẵn:

- `rtx5070ti_16gb`: mặc định, chunk 5 giây, sample 0.4 FPS, BF16, SDPA, NVENC.
- `speed`: nhanh hơn, ít frame hơn.
- `accuracy`: lấy nhiều frame hơn, chậm hơn.

Ví dụ đổi profile:

```bat
python main.py --video static/demo.mp4 --hardware-profile speed --output outputs/result_demo.json
python main.py --video static/demo.mp4 --hardware-profile accuracy --output outputs/result_demo.json
```

## 5. Chạy giao diện web

Chạy:

```bat
run_streamlit.bat
```

Lệnh tương đương:

```bat
call local_env\.venv\Scripts\activate
streamlit run app\streamlit_app.py
```

Sau khi Streamlit hiện URL, mở trình duyệt vào URL đó. Thường là:

```text
http://localhost:8501
```

## 6. Luồng chạy của ứng dụng

1. Người dùng đặt `static/demo.mp4` hoặc upload MP4 trong UI.
2. UI gọi `main.py` thông qua hàm `run_analysis()` trong `app/streamlit_app.py`.
3. `main.py` đọc thông tin video bằng `ffprobe`/OpenCV.
4. `src/video_utils.py` cắt video thành các chunk MP4 trong `outputs/chunks/<video_id>/`.
5. Mỗi chunk được lấy frame theo `sample_fps`.
6. `src/model_runner.py` đưa frame vào model Cosmos-Reason2 để sinh mô tả.
7. `src/result_utils.py` chuẩn hóa output thành segment có `start`, `end`, `start_seconds`, `end_seconds`, `chunk_path`, `description`.
8. `src/summary_utils.py` tạo tóm tắt video và các mốc quan trọng.
9. `src/vector_store.py` index segment vào LanceDB tại `outputs/lancedb`.
10. UI đọc `outputs/result_demo.json`, render video gốc, preview chunk đã cắt, bảng timeline, tóm tắt và tìm kiếm ngữ nghĩa.

## 7. Output quan trọng

```text
outputs/result_demo.json          Kết quả phân tích chính
outputs/chunks/<video_id>/        Video chunk đã cắt
outputs/lancedb/                  Vector index để tìm kiếm
outputs/summaries/                Tóm tắt video
static/demo.mp4                   Video đang được UI sử dụng
```

Mỗi segment trong `outputs/result_demo.json` cần có `chunk_path`. Nếu `chunk_path` tồn tại và file MP4 không rỗng, UI sẽ hiện preview phân đoạn đã cắt.

## 8. Kiểm tra khi video không hiện

- Kiểm tra `static/demo.mp4` có tồn tại và dung lượng lớn hơn 0 byte.
- Kiểm tra `outputs/result_demo.json` có segment và mỗi segment có `chunk_path`.
- Kiểm tra các file trong `outputs/chunks/<video_id>/chunk_*.mp4` có tồn tại.
- Thử mở chunk bằng VLC/Windows Media Player để xác nhận file không hỏng.
- Kiểm tra `ffmpeg` và `ffprobe` trong `PATH`.
- Nếu video upload dùng codec lạ, chạy lại phân tích để chunk được encode lại H.264 `yuv420p`.
- Nếu UI đang mở kết quả cũ, bấm Reset hoặc upload/chạy phân tích lại.

Lệnh kiểm tra nhanh:

```bat
dir static\demo.mp4
dir outputs\chunks /s
type outputs\result_demo.json
```

## 9. Test tìm kiếm demo

Sau khi đã có `outputs/result_demo.json`:

```bat
local_env\.venv\Scripts\python.exe tests\run_demo_search_tests.py --rebuild-index
```

Test sẽ kiểm tra:

- File result có segment.
- Timestamp hợp lệ.
- `chunk_path` tồn tại.
- LanceDB trả kết quả cho các query demo.
- Mỗi match có mốc thời gian và trỏ tới chunk video thật.
