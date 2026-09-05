# Kế hoạch test AI video chiều nay

## Mục tiêu

Hoàn thành một luồng kiểm thử độc lập cho video có sẵn: người vận hành chọn video, hệ thống lưu an toàn vào kho clip, tạo event test và chạy lần lượt phân tích hình ảnh, âm thanh và LLM. Luồng camera/NVR bất thường hiện hữu không thay đổi.

## Phạm vi hoàn thành trong chiều nay

1. Trang admin `/test-ai` có chọn/upload video và giới hạn định dạng/dung lượng.
2. Video được đặt tại `manual-tests/YYYY/MM/DD/`, không lẫn với camera thực.
3. Upload tạo một `video_anomaly` có mã `ManualTest`; có thể mở video, chạy phân tích video và âm thanh như event bất thường.
4. LLM hiển thị kết luận/rủi ro/hành động sau audio pipeline nếu dịch vụ LLM đã cấu hình.
5. Trang chỉ dành cho admin; không mở endpoint upload công khai.

## Kịch bản test

| Lần test | Input | Kết quả cần kiểm tra |
|---|---|---|
| 1 | MP4 có hình + giọng nói | video analysis có tóm tắt; transcript và LLM suggestion xuất hiện |
| 2 | MP4 chỉ có hình | video analysis hoạt động; audio báo không có audio/không có speech rõ ràng |
| 3 | MP4 có tiếng bất thường | STT/audio evidence, mức rủi ro và hành động LLM đúng evidence |
| 4 | File sai định dạng/quá dung lượng | upload bị chặn, không tạo event/file dở dang |
| 5 | Video dài hơn 30 giây | Whisper long-form trả transcript, không HTTP 500 |

## Trình tự vận hành

1. Chạy web app với NAS và PostgreSQL dual-write như cấu hình hiện tại.
2. Đăng nhập admin, mở `/test-ai`, chọn một video mẫu và upload.
3. Phát video, bấm **Phân tích hình ảnh** và **Phân tích âm thanh + LLM**.
4. Ghi lại event ID, thời gian xử lý, kết quả, lỗi (nếu có) vào báo cáo chiều nay.
5. Kiểm tra Data Health: outbox PostgreSQL về `0`, clip test mở được từ NAS.

## Tiêu chí chốt chiều nay

- Ít nhất 3 video mẫu chạy hết luồng, gồm video có tiếng và không tiếng.
- Không làm hỏng event camera thật hoặc dữ liệu NAS đã tổ chức.
- Lỗi upload/AI hiển thị được cho người vận hành, không mất event test.
- Có danh sách kết quả test để báo cáo sếp.

## Không làm hôm nay

- Không đổi PostgreSQL thành nguồn đọc chính.
- Không xóa clip cũ hoặc event camera thật.
- Không mở upload ra Internet/công khai.
