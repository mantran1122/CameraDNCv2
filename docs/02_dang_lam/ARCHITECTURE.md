# Kiến trúc ứng dụng DNC-VSS

## Tổng quan 2 file chính

```
app/streamlit_app.py  ← Entry point, business logic, điều phối
app/ui/dashboard.py   ← UI component library, CSS, render functions
```

`streamlit_app.py` import `app/ui/dashboard.py` dưới alias `ui`:
```python
from app.ui import dashboard as ui
```

---

## Luồng khởi động (`main()` — streamlit_app.py:75)

```
st.set_page_config()
    ↓
init_state()                  # Nạp config.json → session_state (dòng 146)
    ↓
ui.render_page_style()        # Inject toàn bộ CSS vào trang (app/ui/dashboard.py:45)
    ↓
Sidebar:
  logo + radio menu (4 mục)
  render_openai_settings()    # Expander cấu hình LLM (dòng 209)
    ↓
ensure_history_snapshot()     # Auto-lưu result hiện tại vào history (dòng 248)
    ↓
build_ui_api()                # Tạo bridge object UiApi (dòng 185)
    ↓
Auto-start folder monitor     # Nếu config đã bật (dòng 108)
    ↓
Route theo menu đã chọn       # if/elif dòng 115–143
```

---

## Bridge pattern: UiApi

`app/ui/dashboard.py` không gọi trực tiếp bất kỳ hàm nào của `streamlit_app.py`.  
Thay vào đó, `streamlit_app.py` đóng gói toàn bộ business logic thành dataclass `UiApi`
rồi truyền vào các hàm render:

```python
# streamlit_app.py:26–43 (app/ui/dashboard.py định nghĩa interface)
@dataclass
class UiApi:
    semantic_search: Callable
    keyword_search: Callable
    rebuild_index: Callable
    reset_search: Callable
    save_uploaded_video: Callable
    available_server_videos: Callable
    use_server_video: Callable
    run_analysis: Callable
    clear_outputs: Callable
    clear_vector_db: Callable
    has_existing_result: Callable
    clear_video_data: Callable
    save_email_config: Callable
    start_folder_monitor: Callable
    stop_folder_monitor: Callable
    get_folder_monitor_status: Callable

# streamlit_app.py:185 (implementation)
def build_ui_api() -> ui.UiApi:
    return ui.UiApi(
        semantic_search=lambda query, limit, mode: semantic_search(...),
        run_analysis=run_analysis,
        save_email_config=lambda cfg: _save_config(cfg),
        ...  # mỗi field là lambda/hàm trong streamlit_app.py
    )
```

**Kết quả:** `app/ui/dashboard.py` chỉ biết `api.run_analysis(path)` — không cần biết implement thế nào.

---

## 4 mục điều hướng Sidebar

Định nghĩa tại `streamlit_app.py:90–99`:

```python
menu = st.radio("Chức năng", [
    ":material/cloud_upload: Upload Video Mới",
    ":material/manage_search: Tìm Kiếm Toàn Lịch Sử",
    ":material/history: Lịch Sử Phân Tích",
    ":material/assessment: Báo Cáo & Xuất File",
])
```

---

### Mục 1 — Upload Video Mới (`streamlit_app.py:115`)

**Điều kiện phân nhánh:**

```
RESULT_PATH tồn tại?
  ├─ Có → ui.render_result_view(data, video_path, events, ...)
  └─ Không → ui.render_upload_view(VIDEO_PATH, api)
```

**`render_result_view`** (`app/ui/dashboard.py`) — layout 3 cột:

| Cột | Tỉ lệ | Nội dung | Hàm |
|-----|-------|----------|-----|
| Trái | 1.6 | Video player + thông tin đoạn đang chọn | `render_left_column()` |
| Giữa | 1.2 | Danh sách timeline, click để nhảy | `render_middle_column()` |
| Phải | 0.9 | Validation, Search, Filters, Chat, Reset | `render_right_column()` |

Bên dưới 3 cột: `render_video_input_panel()` — upload / chọn từ server / phân tích lại.

**`render_upload_view`** (`app/ui/dashboard.py`) — chỉ hiện panel chọn video, chưa có kết quả.

---

### Mục 2 — Tìm Kiếm Toàn Lịch Sử (`streamlit_app.py:131`)

Hàm: `render_global_search_tab()` (`streamlit_app.py:1626`)  
Toàn bộ nằm trong `streamlit_app.py`, không dùng component từ `app/ui/dashboard.py`.

Luồng:
```
Text area nhập câu hỏi
  + Slider số kết quả
  + Radio chế độ (hybrid_lancedb | openai_metadata)
    ↓
Nút "Tìm trên lịch sử" → semantic_search_global() → LanceDB / OpenAI
    ↓
render_search_results(events)     # bảng kết quả, click → dialog xem video
```

Nút phụ: "Lập chỉ mục lại toàn bộ lịch sử" → `rebuild_vector_index()`

---

### Mục 3 — Lịch Sử Phân Tích (`streamlit_app.py:134`)

Hàm: `render_history_tab()` (`streamlit_app.py:1708`)  
Toàn bộ nằm trong `streamlit_app.py`.

Luồng:
```
load_history_items()   # đọc outputs/history/*.json
  ↓
Danh sách: video_id | video_file | segment_count | overview
  ↓
Nút "Xem chi tiết" → show_video_history_dialog() [@st.dialog]
  → bảng segments + preview video chunks (tối đa 12 đoạn)
```

---

### Mục 4 — Báo Cáo & Xuất File (`streamlit_app.py:137`)

Hàm: `ui.render_report_tab(data, events, api)` (`app/ui/dashboard.py`)  
Đây là mục duy nhất có **4 sub-tab thực sự** bằng `st.tabs()`.

```python
tab_cfg, tab_email, tab_folder, tab_export = st.tabs([
    "📝 Cấu hình Template",
    "📧 Cấu hình Email",
    "📁 Thư mục Input",
    "📊 Xuất Báo cáo",
])
```

| Sub-tab | Hàm | File | Chức năng |
|---------|-----|------|-----------|
| 📝 Cấu hình Template | `render_report_template_config()` | `app/ui/dashboard.py` | Tiêu đề, header, footer, checkbox bật/tắt phần |
| 📧 Cấu hình Email | `render_email_config()` | `app/ui/dashboard.py` | SMTP, sender, password, recipients, ngưỡng rủi ro |
| 📁 Thư mục Input | `render_inprogress_folder_config()` | `app/ui/dashboard.py` | Path folder giám sát + toggle giám sát tự động |
| 📊 Xuất Báo cáo | `render_report_export()` | `app/ui/dashboard.py` | Lọc + xuất Excel/PDF/HTML + gửi email |

---

## Sơ đồ call graph tổng hợp

```
streamlit_app.py: main()
├── ui.render_page_style()
├── Sidebar radio menu
│
├── [Mục 1] ui.render_result_view()          [app/ui/dashboard.py]
│     ├── render_left_column()
│     ├── render_middle_column()
│     └── render_right_column()
│           ├── render_validation_panel()
│           ├── render_search_card()          ← gọi api.semantic_search
│           ├── render_filters()
│           ├── render_chat_box()
│           └── render_reset_panel()          ← gọi api.clear_outputs, api.clear_vector_db
│
├── [Mục 2] render_global_search_tab()        [streamlit_app.py]
│     └── semantic_search_global()
│           └── search_video() [src/vector_store.py]
│
├── [Mục 3] render_history_tab()              [streamlit_app.py]
│     └── load_history_items()
│           └── history_result_files()
│
└── [Mục 4] ui.render_report_tab()            [app/ui/dashboard.py]
      ├── render_report_template_config()
      ├── render_email_config()
      ├── render_inprogress_folder_config()   ← gọi api.start/stop_folder_monitor
      └── render_report_export()
            ├── _export_report_excel()
            ├── _export_report_pdf()
            └── _export_report_html()
```

---

## Config & State

| Nguồn | Mục đích |
|-------|----------|
| `config.json` | Lưu persistent: email, smtp, folder path, report template |
| `st.session_state` | Runtime state: events, search results, selected index, chat history |
| `os.environ` | OPENAI_API_KEY, SMTP_PASSWORD, COSMOS_* settings |
| `outputs/history/*.json` | Lịch sử kết quả phân tích từng video |
| `outputs/analyzed_signatures.json` | Index signature (size+duration) tránh phân tích trùng |

---

## Các file khác liên quan

```
cosmos_code_base/
├── app/
│   ├── streamlit_app.py    ← entry point
│   ├── ui/
│   │   └── dashboard.py    ← UI components
│   └── ui_web.py           ← compatibility import cũ
│   └── __init__.py
├── src/
│   ├── vector_store.py     ← LanceDB: index_result_file, search_video
│   ├── result_utils.py     ← clean_text()
│   └── video_utils.py      ← hhmmss_to_seconds()
├── main.py                 ← analysis subprocess (gọi bằng subprocess.Popen)
├── config.json             ← persistent config
├── static/demo.mp4         ← video hiện tại đang xử lý
└── outputs/
    ├── result_demo.json    ← kết quả phân tích hiện tại
    ├── history/            ← snapshot lịch sử
    └── chunks/             ← video chunks đã cắt
```
