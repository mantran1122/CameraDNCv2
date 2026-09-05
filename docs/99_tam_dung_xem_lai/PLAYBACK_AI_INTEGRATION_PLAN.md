# Kế hoạch tích hợp Playback với phân tích AI trên Streamlit

## 1. Mục tiêu

Giữ nguyên chức năng Playback hiện tại trên ứng dụng Dahua NetSDK:

- Đăng nhập đầu ghi.
- Chọn kênh camera.
- Chọn ngày và khoảng thời gian.
- Phát, tạm dừng và dừng video ngay trên cửa sổ Playback.
- Tải video thủ công như hiện tại.

Chỉ bổ sung một nút mới: **Phân tích AI**.

AI không tự chạy khi người dùng mở Playback, đổi kênh, chọn ngày hoặc bấm phát. Luồng phân tích chỉ được kích hoạt khi người dùng chủ động bấm **Phân tích AI**.

## 2. Trải nghiệm người dùng

1. Người dùng mở chức năng Playback từ `launcher.py`.
2. Đăng nhập đầu ghi và chọn kênh camera.
3. Chọn thời gian bắt đầu và thời gian kết thúc cần kiểm tra.
4. Có thể bấm **Xem lại** để kiểm tra đoạn ghi hình trên ứng dụng như hiện tại.
5. Khi cần AI, người dùng bấm **Phân tích AI**.
6. Ứng dụng tải đúng đoạn video đã chọn từ đầu ghi về máy.
7. File `.dav` của đầu ghi được chuyển sang `.mp4` để trình duyệt và pipeline Cosmos đọc được.
8. Trang Streamlit được mở tại `http://127.0.0.1:8501`.
9. Đoạn MP4 vừa tạo được nạp sẵn vào trang `cosmos_code_base/app/streamlit_app.py`.
10. Phân tích AI bắt đầu cho đúng đoạn video này và kết quả được hiển thị trên web.

Nếu người dùng không bấm **Phân tích AI**, không có video nào được gửi sang Streamlit và Cosmos không phân tích Playback.

## 3. Luồng dữ liệu

```text
Playback trên PyQt
    |
    | Người dùng bấm "Phân tích AI"
    v
NetSDK DownloadByTimeEx
    |
    | video theo kênh + thời gian đã chọn
    v
File tạm .dav
    |
    | FFmpeg chuyển định dạng
    v
File .mp4 trong thư mục handoff
    |
    | manifest JSON + playback token
    v
app/streamlit_app.py
    |
    | nạp video và gọi pipeline main.py
    v
Timeline, mô tả, rủi ro và kết quả tìm kiếm trên web
```

## 4. Phạm vi thay đổi

### 4.1. Playback PyQt

File chính:

`NetSDK_Camera/Demo/PlayBackDemo/PlayBackDemo.py`

Các thay đổi dự kiến:

- Thêm nút **Phân tích AI** vào khu vực chọn khoảng thời gian.
- Nút chỉ được bật khi:
  - Đã đăng nhập đầu ghi.
  - Kênh camera hợp lệ.
  - Thời gian bắt đầu nhỏ hơn thời gian kết thúc.
  - Ngày đã chọn có video lưu.
- Khi bấm nút:
  - Khóa nút để chống bấm lặp.
  - Tải đoạn video bằng `DownloadByTimeEx` vào file tạm `.dav`.
  - Hiển thị tiến độ bằng thanh tiến độ hiện có hoặc thanh tiến độ riêng.
  - Khi tải xong, chạy FFmpeg để chuyển `.dav` sang `.mp4`.
  - Tạo thông tin bàn giao cho Streamlit.
  - Mở trình duyệt sau khi file MP4 đã hoàn tất và có dung lượng hợp lệ.
- Nếu người dùng bấm dừng hoặc đóng cửa sổ, phải dừng download và giải phóng handle NetSDK.

Playback trực tiếp trên `PlayBackWnd` không bị thay đổi.

### 4.2. Thư mục bàn giao video

Thêm thư mục:

`cosmos_code_base/playback_inbox/`

Cấu trúc đề xuất:

```text
playback_inbox/
  playback_ch18_20260819_100000_101000.mp4
  playback_handoff.json
```

File `playback_handoff.json` chứa tối thiểu:

```json
{
  "token": "mã duy nhất của lần yêu cầu",
  "source": "dahua_playback",
  "video_path": "D:\\dnc\\cosmos_code_base\\playback_inbox\\playback_ch18_20260819_100000_101000.mp4",
  "channel": 18,
  "start_time": "2026-08-19T10:00:00+07:00",
  "end_time": "2026-08-19T10:10:00+07:00",
  "auto_analyze": true,
  "created_at": "2026-08-19T10:10:05+07:00"
}
```

Manifest phải được ghi theo kiểu an toàn: ghi file tạm trước, sau đó đổi tên. Streamlit không được đọc file JSON đang ghi dở.

### 4.3. Streamlit

File chính:

`cosmos_code_base/app/streamlit_app.py`

Các thay đổi dự kiến:

- Nhận tham số URL dạng:

```text
http://127.0.0.1:8501/?playback_token=<token>
```

- Đọc `playback_handoff.json` và kiểm tra:
  - Token trên URL khớp token trong manifest.
  - Nguồn là `dahua_playback`.
  - File có phần mở rộng `.mp4`.
  - File nằm trong `playback_inbox`.
  - File tồn tại và dung lượng lớn hơn 0.
- Nạp video này làm video hiện tại thay cho việc yêu cầu người dùng upload lại.
- Xóa trạng thái kết quả của video trước trong phiên web mới.
- Chỉ gọi `run_analysis()` một lần cho mỗi token.
- Lưu token đã xử lý trong `st.session_state` để Streamlit rerun không phân tích lặp lại.
- Hiển thị tên kênh, thời gian bắt đầu và kết thúc của đoạn Playback.
- Nếu phân tích lỗi, giữ video trên trang để người dùng có thể bấm **Bắt đầu phân tích** lại.

## 5. Khởi động trang Streamlit

Khi bấm **Phân tích AI**, ứng dụng kiểm tra `http://127.0.0.1:8501`:

- Nếu Streamlit đang chạy: mở ngay URL có `playback_token`.
- Nếu chưa chạy: khởi động `cosmos_code_base/run_streamlit.bat`, chờ endpoint sẵn sàng rồi mở trình duyệt.
- Nếu quá thời gian chờ: báo lỗi rõ ràng trên Playback và giữ lại file MP4 để người dùng không phải tải lại.

`live_service.py` tại cổng `8765` phục vụ phân tích Live từng ảnh và không phải entry point của luồng Playback này. Phân tích Playback trên web sử dụng `app/streamlit_app.py`, sau đó Streamlit gọi pipeline video trong `main.py`.

## 6. Chuyển DAV sang MP4

Lệnh FFmpeg dự kiến:

```powershell
ffmpeg -y -i input.dav -map 0:v:0 -map 0:a? -c:v copy -c:a aac output.mp4
```

Nếu camera dùng codec/container không thể remux trực tiếp, dùng phương án dự phòng:

```powershell
ffmpeg -y -i input.dav -map 0:v:0 -map 0:a? -c:v libx264 -preset fast -crf 23 -c:a aac output.mp4
```

Chỉ mở Streamlit sau khi `ffprobe` xác nhận MP4 có video stream và thời lượng lớn hơn 0.

## 7. Quy tắc không phân tích ngoài ý muốn

- Không phân tích khi mở cửa sổ Playback.
- Không phân tích khi đăng nhập đầu ghi.
- Không phân tích khi chọn kênh hoặc ngày.
- Không phân tích khi bấm **Xem lại**.
- Không phân tích khi bấm **Tải xuống** thủ công.
- Chỉ phân tích khi bấm **Phân tích AI**.
- Mỗi lần bấm tạo một token riêng và chỉ được xử lý một lần.
- Streamlit rerun, refresh hoặc thay đổi bộ lọc không được chạy lại model cho cùng token.

## 8. Xử lý lỗi bắt buộc

- Không có bản ghi trong khoảng đã chọn: không tải, không mở web.
- Thời gian không hợp lệ: báo lỗi ngay trên Playback.
- Đầu ghi mất kết nối: dừng tiến trình và mở lại nút.
- Download thất bại: xóa file tạm không hoàn chỉnh.
- Thiếu FFmpeg: báo vị trí cần cài hoặc cấu hình `COSMOS_FFMPEG`.
- Chuyển MP4 thất bại: giữ `.dav` để kiểm tra, không gửi file lỗi sang web.
- Streamlit không khởi động: giữ MP4 và hiển thị đường dẫn file.
- Pipeline AI lỗi: Streamlit vẫn phát được video và cho phép chạy lại thủ công.

## 9. Các lỗi Playback nên sửa trong cùng đợt

- `QueryRecordFile` phải dùng kênh đang chọn, không được cố định kênh `0`.
- Đồng bộ ngày trên lịch vào ô thời gian bắt đầu và kết thúc.
- Không bỏ qua bản ghi cuối một cách cố định.
- Không đặt `downloadID = 0` trước khi gọi `StopDownload`.
- Đóng cửa sổ phải dừng cả playback và download trước khi logout.
- Chặn khoảng thời gian quá dài để tránh tải nhầm video nhiều giờ.

Giới hạn ban đầu đề xuất cho một yêu cầu AI là 30 phút. Có thể cấu hình bằng biến môi trường sau:

```text
COSMOS_PLAYBACK_MAX_MINUTES=30
```

## 10. Tiêu chí nghiệm thu

1. Mở Playback và xem lại video bình thường mà Cosmos không chạy phân tích.
2. Chọn đúng kênh và khoảng thời gian, bấm **Phân tích AI**.
3. Chỉ đoạn đã chọn được tải từ đầu ghi.
4. File MP4 phát được bằng trình duyệt.
5. Streamlit tự mở và hiển thị đúng video, kênh và thời gian.
6. AI chỉ chạy một lần cho token vừa tạo.
7. Refresh trang không làm AI chạy lại.
8. Một lần bấm mới tạo yêu cầu phân tích mới.
9. Video trước không bị phân tích nhầm thay cho video vừa tải.
10. Lỗi download, FFmpeg hoặc Streamlit đều được báo rõ, không làm treo Playback.

## 11. Thứ tự triển khai

1. Sửa lựa chọn kênh và khoảng thời gian trong Playback.
2. Thêm nút **Phân tích AI** và luồng tải file tạm.
3. Thêm chuyển đổi DAV sang MP4 và kiểm tra bằng ffprobe.
4. Thêm manifest/token bàn giao.
5. Thêm cơ chế nhận Playback vào `app/streamlit_app.py`.
6. Thêm khởi động/mở Streamlit từ Playback.
7. Viết kiểm thử token, chống phân tích lặp và kiểm tra đường dẫn.
8. Kiểm thử tích hợp với đầu ghi thật trên máy chủ.
