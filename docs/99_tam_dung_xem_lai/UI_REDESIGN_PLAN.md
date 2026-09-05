# Kế hoạch nâng cấp giao diện DNC-VSS

## Mục tiêu

Làm giao diện gọn, hiện đại và dễ thao tác khi theo dõi video giám sát; **giữ tone xanh teal hiện có**. Không thay đổi luồng phân tích, dữ liệu hay API.

## Vấn đề cần xử lý

- Quá nhiều khung, viền, tab và nút xuất hiện cùng lúc nên khó xác định thao tác chính.
- Các khu vực Video, Timeline, tìm kiếm và lọc chưa có thứ bậc thị giác rõ ràng.
- Sidebar đang có nhiều CSS can thiệp sâu vào Streamlit, dễ gây cảm giác nặng và vỡ layout khi cập nhật thư viện.
- Card, badge và khoảng cách dùng nhiều biến thể; cần thống nhất thành một hệ thống nhỏ.
- Các hành động nguy hiểm (xóa dữ liệu) cần được tách xa thao tác thường xuyên.

## Hướng thiết kế

### 1. Giữ màu, giảm độ nặng

Giữ nguyên các token trong `app/ui/templates/dashboard.css`:

- Primary teal: `--accent`, `--accent-2`.
- Nền teal nhạt: `--accent-soft`.
- Risk thấp / trung bình / cao: các token `--risk-*` hiện có.

Điều chỉnh cách dùng:

- Teal đậm chỉ cho nút chính, trạng thái đang chọn và điểm nhấn quan trọng.
- Teal nhạt chỉ dùng cho active state hoặc vùng thông tin, không dùng cho mọi card.
- Card nền trắng, border mảnh; bỏ shadow ở card phụ.
- Chỉ dùng màu rủi ro cho badge và thanh trạng thái, không phủ cả card.

### 2. Bố cục trang Phân tích video

```
Header gọn: tên video + trạng thái phân tích + hành động chính
├─ Video player (rộng, vùng trọng tâm)
├─ Thanh điều khiển: Upload | Chọn video server | Phân tích lại
└─ Khu vực dưới video
   ├─ Timeline / danh sách sự kiện (2/3 chiều rộng)
   └─ Inspector (1/3): chi tiết segment đang chọn + tìm kiếm/lọc
```

- Khi chưa có kết quả: chỉ hiển thị khu vực chọn video ở giữa trang, không hiển thị panel trống.
- Khi có kết quả: bỏ hero lớn để dành diện tích cho video.
- Đặt nút **Phân tích** gần phần chọn video; chỉ một primary button trên màn hình.
- Timeline luôn thấy được; tìm kiếm và lọc đặt trong cùng một panel thu gọn.
- Đặt lại/xóa dữ liệu chuyển vào menu `…` hoặc expander cuối trang.

### 3. Sidebar

- Logo nhỏ, một dòng tên hệ thống, không dùng banner lớn.
- Menu dạng danh sách icon + nhãn, active state nền teal nhạt; bỏ animation trượt và CSS ẩn icon native.
- Cấu hình LLM chuyển xuống cuối sidebar và mặc định đóng.
- Chiều rộng sidebar cố định, tránh card bao quanh từng mục menu.

### 4. Component chuẩn hóa

| Thành phần | Quy tắc |
|---|---|
| Card | Radius 10px, border `--border`, padding 16px, không shadow hoặc chỉ shadow nhẹ cho card chính |
| Nút primary | Teal đậm, một nút chính/màn hình |
| Nút secondary | Nền trắng, border mảnh |
| Badge rủi ro | Nhỏ, chỉ gồm chấm màu + nhãn |
| Typography | Tiêu đề trang 24px; tiêu đề section 16px; nội dung 14px; metadata 12px |
| Spacing | Hệ 4 / 8 / 12 / 16 / 24px; không dùng spacer HTML rải rác |

### 5. Timeline và chi tiết sự kiện

- Mỗi event tối đa 2 dòng: thời gian + risk/chip ở dòng 1; mô tả rút gọn ở dòng 2.
- Không cần nút “Xem” chiếm toàn bộ chiều rộng ở từng event: click toàn bộ event để chọn, có tooltip hướng dẫn.
- Event được chọn có nền teal nhạt và viền trái teal 3px.
- Panel Inspector hiển thị mô tả đầy đủ, action chip, mức rủi ro và nút “Nhảy đến thời điểm”.

### 6. Responsive và khả dụng

- Màn hình dưới 1024px: xếp Video → Inspector → Timeline theo một cột.
- Text tối thiểu 12px; giữ tương phản màu chữ/risk badge dễ đọc.
- Không chỉ dựa vào màu cho trạng thái rủi ro: luôn có nhãn LOW/MEDIUM/HIGH.
- Có loading state rõ ràng khi upload, index và phân tích.

## Kế hoạch triển khai

1. **Dọn CSS nền tảng**: giữ các color token, thay hệ spacing/card/button và bỏ CSS hack sidebar.
2. **Sắp xếp lại trang Phân tích**: tạo layout Video + Timeline + Inspector theo wireframe trên.
3. **Rút gọn hành động**: gom filter/search, đưa reset vào khu vực phụ.
4. **Chuẩn hóa các trang còn lại**: Lịch sử, tìm kiếm toàn cục, báo cáo dùng cùng card/header/button.
5. **Thêm motion & loading feedback**: theo đặc tả bên dưới, ưu tiên các trạng thái có thời gian chờ.
6. **Kiểm thử**: desktop 1366px, laptop 1024px, mobile/tablet; kiểm tra luồng upload → phân tích → chọn segment → xuất báo cáo.

## File cần sửa và trách nhiệm

| File | Cần thay đổi | Mức độ |
|---|---|---|
| `app/ui/templates/dashboard.css` | Token spacing/elevation; style layout mới; responsive; toàn bộ animation/keyframe; bỏ CSS sidebar can thiệp quá sâu | Cao |
| `app/ui/dashboard.py` | Sắp xếp lại hàm `render_result_view`, `render_video_input_panel`, `_render_timeline_new`, `render_left_column`, `render_right_panel`; thêm class/state cho loading và selected event | Cao |
| `app/ui/templates/timeline_segment.html` | Làm event card có vùng click lớn, active/hover state, trạng thái chọn rõ | Trung bình |
| `app/ui/templates/current_segment.html` | Đổi thành Inspector gọn: rủi ro, thời gian, mô tả, action chips và nút nhảy video | Trung bình |
| `app/ui/templates/stats_row.html` | Giảm từ bốn card nặng xuống metric strip hoặc 2×2 khi màn hình hẹp | Trung bình |
| `app/ui/templates/header.html` | Thu gọn thành app header; chỉ hiện tên video/trạng thái ở trang đã có kết quả | Thấp |
| `app/ui/templates/spinner.html` *(tạo mới)* | Skeleton/loading indicator dùng lại cho upload, tải kết quả và tìm kiếm | Trung bình |
| `app/ui/templates/empty_state.html` *(tạo mới)* | Empty state thống nhất cho chưa có video, chưa có lịch sử, không có kết quả lọc | Thấp |
| `app/ui/templates/toast.html` *(tạo mới, nếu cần)* | Thông báo hoàn tất/thất bại đồng nhất; ưu tiên `st.toast` nếu Streamlit đáp ứng đủ | Thấp |
| `app/streamlit_app.py` | Bổ sung và quản lý `session_state` cho `is_loading`, `analysis_progress`, `selected_event_index`; bọc các tác vụ upload/search/analyze bằng trạng thái UI | Cao |
| `app/ui_web.py` | Không cần sửa giao diện; chỉ giữ compatibility import | Không sửa |
| `app/ui/templates/*.html` khác | Chỉ chỉnh khi cần đồng nhất class, spacing và component | Thấp |

> Không sửa `src/`, `backend/`, luồng phân tích video, vector DB hoặc định dạng dữ liệu trong đợt redesign UI này.

## Motion, loading và phản hồi thị giác

Mục tiêu là giao diện có cảm giác “sống” nhưng không gây phân tâm trong môi trường giám sát. Dùng transition 120–220ms, tránh animation lặp vô hạn ngoài trạng thái đang xử lý.

| Tình huống | Hiệu ứng đề xuất | Cách triển khai |
|---|---|---|
| Mở trang / chuyển menu | Nội dung fade + dịch lên 4px, 160ms | CSS `@keyframes page-enter`; thêm class cho main container |
| Hover card / timeline event | Nền sáng hơn, border teal nhạt, nâng 1px | `transition: background, border-color, transform 160ms ease` |
| Chọn event | Viền trái teal animate từ 0 → 3px; nền teal nhạt | `.is-active` + `@keyframes selected-event` |
| Click nút | Scale xuống 0.98 trong 80ms, trở lại trong 120ms | `button:active { transform: scale(.98) }` |
| Upload video | Dropzone đổi màu viền; file thành công hiện checkmark và fade-in | State `uploading` / `uploaded` trong `dashboard.py` |
| Đang tìm kiếm | Skeleton 2–3 dòng trong kết quả; thay bằng kết quả qua fade 150ms | Template `spinner.html`; không để vùng kết quả trống |
| Đang phân tích video | Progress bar teal có nhãn giai đoạn, thời gian đã chạy và animation shimmer nhẹ | Dùng dữ liệu `analysis_progress` đã có trong `streamlit_app.py` |
| Hoàn tất phân tích | Toast thành công + card summary fade-in; không tự cuộn trang | `st.toast` và class `result-enter` |
| Lỗi | Viền đỏ nhạt + icon, không rung layout | Streamlit `st.error`; CSS cho error panel nếu cần |
| Không có dữ liệu | Minh họa/icon đơn sắc teal nhạt + CTA duy nhất | `empty_state.html` |

### Quy tắc motion

- Tôn trọng `@media (prefers-reduced-motion: reduce)`: tắt transition/animation không cần thiết.
- Không dùng carousel, parallax, gradient chạy liên tục, hay bounce animation.
- Spinner chỉ xuất hiện khi thao tác kéo dài trên ~300ms; tác vụ ngắn dùng trạng thái nút disabled + label “Đang lưu…”.
- Progress phải phản ánh tiến trình thật; không dùng thanh chạy vô hạn cho phân tích video nếu đã có phần trăm/giai đoạn.

### CSS tối thiểu cần bổ sung trong `dashboard.css`

```css
@keyframes page-enter { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
@keyframes shimmer { from { background-position: 200% 0; } to { background-position: -200% 0; } }
.result-enter { animation: page-enter 160ms ease-out both; }
.skeleton { background: linear-gradient(90deg, var(--surface-2) 25%, var(--accent-soft) 50%, var(--surface-2) 75%); background-size: 200% 100%; animation: shimmer 1.2s linear infinite; }
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; } }
```

## Tiêu chí hoàn thành

- Người dùng nhìn thấy video, event đang chọn và nút hành động chính mà không phải cuộn.
- Mỗi trang chỉ có một điểm nhấn teal primary rõ ràng.
- Không còn spacer HTML rải rác; khoảng cách được kiểm soát bằng CSS/layout.
- Các thao tác xóa không cạnh tranh thị giác với thao tác phân tích và tìm kiếm.
- Tone teal, nền sáng và màu rủi ro hiện tại được giữ nguyên.
