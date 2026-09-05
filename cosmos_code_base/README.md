# Cosmos Video Analyzer

Ung dung phan tich video giam sat theo timeline, tao mo ta segment, tom tat video va tim kiem ngu nghia bang LanceDB.

Huong dan chi tiet bo sung: `HUONG_DAN_CHAY_DU_AN.md`

## 1) Yeu cau he thong

- OS: Windows 10/11
- Python: 3.11 (khuyen nghi dung `py -3.11`)
- GPU: NVIDIA (khuyen nghi VRAM >= 12GB cho model `nvidia/Cosmos-Reason2-2B`)
- Bat buoc co `ffmpeg` va `ffprobe` trong `PATH`

Kiem tra nhanh:

```bat
py -3.11 --version
ffmpeg -version
ffprobe -version
```

## 2) Cai dat nhanh (khuyen nghi)

```bat
install_D.bat
```

Script se:

- Tao venv tai `local_env\\.venv`
- Cai PyTorch CUDA (`cu130`, fallback `cu128`)
- Cai dependency trong `requirements.txt`
- Tao cache local trong `local_env/`

## 3) Chay du an

Phan tich CLI:

```bat
run_analyze.bat
```

Chay giao dien Streamlit:

```bat
run_streamlit.bat
```

Luu y quan trong: `run_streamlit.bat` da duoc chinh de ep dung dung interpreter:

```bat
local_env\.venv\Scripts\python.exe -m streamlit run app\streamlit_app.py
```

Dieu nay tranh loi chay nham `streamlit` global.

### 3.1) Demo chuyen am thanh thanh text tu video

Neu muon test nhanh mot demo phan tich am thanh tu video da chon, chay:

```bat
call local_env\.venv\Scripts\activate
streamlit run app\audio_to_text_demo.py
```

Demo nay cho phep:

- Chon file video tu may (upload hoac nhap duong dan local)
- Trich xuat audio bang ffmpeg
- Dung Whisper de chuyen thanh text
- Hien ket qua transcript va phan theo tung doan thoi gian
- Tai file text ket qua ve may

Ket qua se duoc luu trong `outputs\audio_demo\`.

## 4) Dependency va version

### 4.1 Requirements khai bao trong repo

Noi dung `requirements.txt` hien tai:

- `transformers>=4.56.0`
- `accelerate`
- `safetensors`
- `sentencepiece`
- `protobuf`
- `opencv-python`
- `pillow`
- `numpy`
- `tqdm`
- `compressed-tensors`
- `huggingface-hub`
- `streamlit`
- `openai`
- `lancedb`
- `sentence-transformers`
- `vllm`

### 4.2 Version da xac nhan trong `local_env\.venv` (ngay 2026-04-29)

| Package | Requirement | Installed |
|---|---|---|
| transformers | `>=4.56.0` | `5.6.2` |
| accelerate | unpinned | `1.13.0` |
| safetensors | unpinned | `0.7.0` |
| sentencepiece | unpinned | `0.2.1` |
| protobuf | unpinned | `7.34.1` |
| opencv-python | unpinned | `4.13.0.92` |
| pillow | unpinned | `12.2.0` |
| numpy | unpinned | `2.4.4` |
| tqdm | unpinned | `4.67.3` |
| compressed-tensors | unpinned | `0.15.0.1` |
| huggingface-hub | unpinned | `1.12.0` |
| streamlit | unpinned | `1.56.0` |
| openai | unpinned | `2.32.0` |
| lancedb | unpinned | `0.30.2` |
| sentence-transformers | unpinned | `5.4.1` |
| vllm | unpinned | **NOT FOUND** |

### 4.3 Core runtime da xac nhan

- `torch==2.11.0+cu130`
- `torchvision==0.26.0+cu130`
- `torchaudio==2.11.0+cu130`

## 5) Khac phuc loi dependency

Neu gap loi:

- `Missing dependency lancedb`
- `Missing dependency sentence-transformers`

Lam theo thu tu:

1. Chay lai `install_D.bat`
2. Chac chan app chay bang `local_env\\.venv\\Scripts\\python.exe`
3. Kiem tra nhanh:

```bat
local_env\.venv\Scripts\python.exe -c "import lancedb, sentence_transformers; print('ok')"
```

Neu can cai bo sung thu cong:

```bat
local_env\.venv\Scripts\python.exe -m pip install --upgrade -r requirements.txt
```

## 6) Cau truc chinh

```text
cosmos_code_base/
├─ app/
│  └─ streamlit_app.py
├─ src/
│  ├─ model_runner.py
│  ├─ result_utils.py
│  ├─ vector_store.py
│  └─ video_utils.py
├─ main.py
├─ run_analyze.bat
├─ run_streamlit.bat
├─ install_D.bat
└─ requirements.txt
```
