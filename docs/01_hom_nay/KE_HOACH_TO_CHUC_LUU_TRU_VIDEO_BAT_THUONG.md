# Kế hoạch tổ chức lưu trữ video bất thường

## 1. Mục tiêu và nguyên tắc

Chuẩn hóa toàn bộ video bất thường để có thể tìm đúng video theo **camera, thời gian và sự kiện**, bất kể người dùng chọn lưu tại máy chủ nội bộ, NAS hay đám mây.

- Video là tệp lớn; **không lưu video trực tiếp trong PostgreSQL**.
- PostgreSQL là nơi quản lý metadata, quyền truy cập, trạng thái đồng bộ và vị trí lưu tệp.
- Mỗi video thuộc đúng một `camera_id`; camera khác không được ghi chung thư mục.
- Đường dẫn vật lý luôn có phân cấp `camera / năm / tháng / ngày`.
- Mọi thao tác ghi, đọc, xóa và chuyển nơi lưu phải đi qua dịch vụ lưu trữ; không để các module tự tạo đường dẫn tùy ý.
- Múi giờ chuẩn: `Asia/Ho_Chi_Minh` (`+07:00`); thời gian trong DB lưu dạng `timestamptz`.

## 2. Kiến trúc đề xuất

```text
Camera/NVR → Event + clip worker → Storage service ─┬→ Ổ cục bộ (tùy chọn)
                                                     ├→ NAS (khuyến nghị kho chính)
                                                     └→ Cloud object storage (bản sao/lưu dài hạn)
                                      │
                                      └→ PostgreSQL: metadata, index, quyền, trạng thái
```

Người dùng chỉ chọn **chính sách lưu** cho camera hoặc hệ thống (ví dụ `nas_only`, `cloud_only`, `nas_then_cloud`). Ứng dụng tự quyết định đường dẫn và ghi nhận kết quả từng đích lưu.

### Các chế độ lưu

| Chế độ | Khi dùng | Quy tắc |
|---|---|---|
| `local_only` | thử nghiệm, máy đơn | không dùng cho môi trường vận hành lâu dài |
| `nas_only` | cần xem nhanh trong LAN | NAS là bản chính, phải sao lưu NAS |
| `cloud_only` | không có NAS, cần truy cập từ xa | dùng bucket riêng tư, không public URL |
| `nas_then_cloud` | khuyến nghị | ghi NAS trước, đồng bộ cloud bất đồng bộ |
| `local_then_nas_then_cloud` | mạng/NAS đôi lúc gián đoạn | local chỉ là hàng đợi tạm, có giới hạn dung lượng và dọn sau khi xác nhận |

**Khuyến nghị ban đầu:** `nas_then_cloud`: NAS phục vụ xem lại nhanh, cloud là bản sao và lưu dài hạn. Nếu ngân sách cloud hạn chế, chỉ đẩy clip bất thường đã xác thực hoặc clip có mức độ rủi ro cao.

## 3. Chuẩn định danh và cây thư mục

Không dùng tên hiển thị camera làm định danh. Mỗi camera có một mã bất biến, ví dụ `cam-001`, `cam-002`.

```text
{storage-root}/abnormal-videos/
  cameras/
    cam-001/
      2026/
        09/
          04/
            evt_cam-001_20260904T103015+0700_8f3a2c1d.mp4
            evt_cam-001_20260904T103015+0700_8f3a2c1d.json
    cam-002/
      2026/
        09/
          04/
            ...
```

Mẫu khóa/đường dẫn tương đối:

```text
abnormal-videos/cameras/{camera_id}/{YYYY}/{MM}/{DD}/evt_{camera_id}_{YYYYMMDDTHHMMSS+0700}_{event_id}.mp4
```

- Tệp sidecar `.json` là tùy chọn, phục vụ kiểm tra/khôi phục; dữ liệu nghiệp vụ chính vẫn ở PostgreSQL.
- `event_id` dùng UUID hoặc ULID để chống trùng khi hai sự kiện xảy ra cùng giây.
- Không nhét thông tin nhạy cảm như tên người vào tên file hay object key.

## 4. PostgreSQL: nguồn tra cứu duy nhất

Đổi sang **PostgreSQL** là phù hợp khi cần nhiều camera, nhiều người dùng, truy vấn theo thời gian và theo dõi đồng bộ. SQLite có thể giữ làm cache cục bộ cho worker nếu cần, nhưng không là nguồn dữ liệu chính.

### Bảng tối thiểu

| Bảng | Vai trò | Trường chính |
|---|---|---|
| `cameras` | danh mục camera | `id`, `code` (unique), `name`, `channel`, `active`, `storage_policy_id` |
| `abnormal_events` | một sự kiện bất thường | `id`, `camera_id`, `occurred_at`, `event_type`, `severity`, `source_event_id`, `status`, `raw_metadata jsonb` |
| `video_assets` | một clip/video của sự kiện | `id`, `event_id`, `camera_id`, `started_at`, `ended_at`, `duration_seconds`, `size_bytes`, `sha256`, `format`, `status` |
| `video_replicas` | vị trí bản sao của video | `id`, `video_asset_id`, `storage_backend`, `object_key`, `state`, `verified_at`, `last_error` |
| `storage_policies` | lựa chọn lưu của người dùng | `id`, `name`, `primary_backend`, `replica_backends`, `retention_days` |
| `audit_logs` | truy vết thao tác | `actor_id`, `action`, `resource_type`, `resource_id`, `created_at`, `details jsonb` |

Ràng buộc quan trọng:

```sql
-- camera không được lẫn video
ALTER TABLE video_assets
  ADD CONSTRAINT video_asset_camera_matches_event
  FOREIGN KEY (event_id, camera_id)
  REFERENCES abnormal_events (id, camera_id);

CREATE UNIQUE INDEX uq_event_source
  ON abnormal_events (camera_id, source_event_id)
  WHERE source_event_id IS NOT NULL;

CREATE INDEX ix_event_camera_time
  ON abnormal_events (camera_id, occurred_at DESC);
CREATE INDEX ix_asset_camera_time
  ON video_assets (camera_id, started_at DESC);
```

> Khi triển khai khóa ngoại ghép ở trên, `abnormal_events` cần thêm ràng buộc `UNIQUE (id, camera_id)`.

`video_replicas.object_key` chỉ lưu đường dẫn tương đối/key object, không lưu đường dẫn Windows tuyệt đối. Việc ánh xạ `nas://`, S3-compatible (MinIO/S3), hay local do cấu hình backend xử lý.

## 5. Luồng ghi và truy xuất

1. Camera/NVR phát hiện bất thường; hệ thống chuẩn hóa và tạo `abnormal_event` với `camera_id`.
2. Clip worker lấy clip, ghi vào thư mục staging cục bộ theo `event_id`.
3. Worker kiểm tra định dạng, thời lượng, dung lượng và tính `sha256`.
4. Storage service tạo đường dẫn chuẩn từ `camera_id` và `occurred_at`, sau đó ghi bản chính vào backend theo policy.
5. Chỉ khi backend trả về thành công, tạo/cập nhật `video_asset` và `video_replica(state='available')` trong PostgreSQL.
6. Tác vụ nền tạo bản sao NAS/cloud, kiểm tra checksum và đánh dấu `verified_at`.
7. UI tìm kiếm theo camera/ngày/sự kiện qua PostgreSQL; backend phát URL tải/xem tạm thời (signed URL hoặc stream proxy), không để client tự biết thông tin đăng nhập NAS/cloud.

Nếu NAS hoặc cloud lỗi: sự kiện vẫn tồn tại, replica mang trạng thái `pending`/`failed`, có retry theo hàng đợi. Không đánh dấu video đã lưu thành công khi chưa kiểm tra checksum.

## 6. Quản lý quyền và tính toàn vẹn

- Phân quyền tối thiểu theo vai trò: `admin`, `operator`, `viewer`, và giới hạn camera nếu cần.
- Service account ghi NAS/cloud có quyền tối thiểu trong đúng prefix `abnormal-videos/`.
- Bucket cloud bật mã hóa at-rest, versioning (nếu khả dụng) và lifecycle; tuyệt đối không public bucket.
- Ghi hash SHA-256, kích thước và thời lượng để phát hiện file thiếu/hỏng.
- Log các hành động xem, tải, xóa, đổi policy và phát hành URL tạm.
- Xóa theo retention chỉ là soft-delete trước; worker xóa file sau thời gian chờ và ghi audit log. Không xóa trực tiếp từ file explorer.

## 7. Chính sách lưu giữ đề xuất (cần người quản trị chốt)

| Loại dữ liệu | NAS | Cloud | Ghi chú |
|---|---:|---:|---|
| Clip bất thường mức bình thường | 90 ngày | 180 ngày | có thể điều chỉnh theo dung lượng/quy định |
| Clip mức cao/đã xác nhận | 180 ngày | 365 ngày | cân nhắc lưu lâu hơn theo nghiệp vụ |
| Metadata và audit log | 365 ngày trở lên | backup DB hằng ngày | nhẹ hơn video, hữu ích khi điều tra |
| File staging local | tối đa 24 giờ sau khi đồng bộ | không áp dụng | tự cảnh báo khi gần đầy ổ |

## 8. Kế hoạch dọn và di chuyển dữ liệu hiện tại

### Pha 0 — Không thay đổi/xóa dữ liệu cũ

- Chụp danh sách toàn bộ thư mục video hiện có, số file, dung lượng, phần mở rộng, mốc thời gian và camera suy đoán được.
- Đưa dữ liệu mới vào chế độ chỉ-ghi theo chuẩn mới; dữ liệu cũ vẫn đọc được ở chế độ tương thích.
- Sao lưu trước khi di chuyển; không dùng thao tác cắt/dán trực tiếp.

### Pha 1 — Chốt cấu hình

- Lập danh sách `camera_id` bất biến và ánh xạ từ tên/IP/channel hiện tại.
- Chốt NAS path, cloud provider/bucket, policy mặc định, quota và thời gian retention.
- Tạo PostgreSQL, migration schema, tài khoản dịch vụ và secret ngoài mã nguồn.

### Pha 2 — Xây storage service

- Một API nội bộ: `store_clip`, `get_playback_url`, `replicate`, `verify`, `retire`.
- Viết adapter riêng cho `local`, `nas` và `s3-compatible`/cloud; các worker không truy cập ổ đĩa trực tiếp.
- Bổ sung queue retry, idempotency theo `event_id`/`sha256`, metrics dung lượng và cảnh báo lỗi đồng bộ.

### Pha 3 — Di chuyển có kiểm soát

1. Quét file cũ và sinh **manifest**: `old_path`, camera suy đoán, thời gian, hash, dung lượng, kết quả.
2. File không xác định camera/thời gian đưa vào hàng `needs_review`, tuyệt đối không đoán rồi lẫn camera.
3. Sao chép sang đích mới; kiểm chứng `sha256` và khả năng phát video.
4. Ghi metadata + replica vào PostgreSQL theo transaction/idempotency.
5. Chạy thử với một camera và một vài ngày trước; đối soát số file, checksum, tìm kiếm UI.
6. Chuyển lần lượt từng camera; chỉ dừng đường ghi cũ sau khi vận hành ổn định.

### Pha 4 — Vận hành

- Hàng ngày: kiểm tra replica lỗi, queue retry, dung lượng NAS/local, backup PostgreSQL.
- Hàng tuần: kiểm tra ngẫu nhiên checksum/phát video từ NAS và cloud.
- Hàng tháng: rà retention, quyền truy cập và báo cáo dữ liệu mồ côi (file không có DB record hoặc ngược lại).

## 9. Tiêu chí hoàn thành giai đoạn đầu

- Tạo event từ bất kỳ camera nào đều sinh file đúng cây thư mục, không lẫn `camera_id`.
- Tìm được video theo camera + ngày trong PostgreSQL, và mở lại được từ UI.
- Mỗi clip có ít nhất một replica `available`; policy `nas_then_cloud` có hai replica đã kiểm checksum.
- Có retry và cảnh báo khi NAS/cloud mất kết nối; không mất event metadata.
- Dữ liệu cũ có manifest, trạng thái di chuyển rõ ràng và không bị xóa ngoài quy trình retention.

## 9.1. Trạng thái triển khai hiện tại (04-09-2026)

Đã triển khai lớp lưu clip chuẩn trong `CameraAI`:

- Clip mới của worker được đặt tại `storage/clips/cameras/cam-XXX/YYYY/MM/DD/evt_cam-XXX_YYYYMMDDTHHMMSS_event-id.mp4`.
- Các đường dẫn clip trong database là đường dẫn tương đối, được kiểm tra để không thể đi ra ngoài thư mục lưu trữ.
- Công cụ `migrate_video_storage.py` mặc định chỉ tạo manifest, không sao chép, không đổi database và không xóa dữ liệu gốc.
- Khi dùng `--apply`, công cụ chỉ **copy** file, so SHA-256 nguồn/đích, rồi mới đổi tham chiếu DB. File legacy được giữ nguyên để rollback.

Lệnh kiểm kê an toàn:

```powershell
python CameraAI\migrate_video_storage.py
```

Lệnh áp dụng (chỉ chạy sau khi duyệt manifest và đã sao lưu):

```powershell
python CameraAI\migrate_video_storage.py --apply
```

Manifest được ghi vào `CameraAI/storage/migrations/`. Các file không liên kết được với event sẽ có trạng thái `needs_review`, không bị tự động đưa vào camera bất kỳ.

### Chuyển kho clip sang NAS

`CAMERAAI_CLIPS_DIR` là biến môi trường cho thư mục gốc clip. Database vẫn ở `CameraAI/storage`; các đường dẫn clip trong database là tương đối nên không phải đổi lại khi chuyển kho.

Ví dụ trên Windows (chỉ sau khi đã copy và kiểm tra dữ liệu NAS):

```powershell
$env:CAMERAAI_CLIPS_DIR = "\\nas01\camera-ai\clips"
python CameraAI\main.py
```

Tài khoản chạy CameraAI phải có quyền đọc/ghi tại NAS. Không xóa bản cũ trước khi UI mở được clip từ NAS và số lượng/checksum đã được đối soát.

### Nhập metadata SQLite sang PostgreSQL

PostgreSQL chỉ lưu metadata và đường dẫn tương đối; video vẫn nằm trên NAS. Tool nhập là idempotent theo `legacy_event_id`, nên có thể chạy lại an toàn sau khi xử lý lỗi mạng.

```powershell
# Kiểm kê SQLite, không ghi PostgreSQL
python CameraAI\migrate_sqlite_to_postgres.py

# Sau khi PostgreSQL đã được tạo và ứng dụng đã cài psycopg
$env:CAMERAAI_POSTGRES_URL = "postgresql://cameraai:MAT_KHAU@localhost:5432/cameraai"
python CameraAI\migrate_sqlite_to_postgres.py --apply --storage-backend nas_primary
```

Không commit URL/mật khẩu database vào Git. Sau khi nhập, đối chiếu số `events`, `events_with_clip`, `audio_analyses` và `video_analyses` trước khi chuyển app sang đọc/ghi PostgreSQL.

### Giai đoạn dual-write

Sau khi đã nhập và đối chiếu PostgreSQL, bật dual-write khi khởi động CameraAI:

```powershell
$env:CAMERAAI_POSTGRES_URL = "host=127.0.0.1 port=5432 dbname=cameraai user=cameraai password='MAT_KHAU'"
$env:CAMERAAI_POSTGRES_DUAL_WRITE = "1"
python CameraAI\main.py
```

SQLite vẫn là nguồn đọc trong giai đoạn này. Mỗi event/clip/audio/video analysis được ghi SQLite trước, sau đó vào hàng đợi `postgres_sync_outbox` để PostgreSQL upsert. Khi PostgreSQL mất kết nối, event không mất; worker retry mỗi 30 giây. Chỉ chuyển PostgreSQL thành nguồn đọc sau khi hàng đợi về 0 và số lượng được đối chiếu qua một thời gian vận hành.

### Report đối chiếu dữ liệu (chỉ đọc)

Khi Data Health có `mismatch` hoặc clip thiếu, tạo report chi tiết trước khi quyết định sửa/xóa bất kỳ dữ liệu nào:

```powershell
python CameraAI\reconcile_data_stores.py
```

Report JSON chứa từng `legacy_event_id` chỉ có ở SQLite/PostgreSQL và từng clip reference không mở được từ NAS. Report nằm ở `CameraAI/storage/reconciliation/` và không thay đổi database hay video.

### Phân tích AI video theo chuỗi thời gian

Phân tích clip không dùng ba ảnh tĩnh cố định nữa. CameraAI chia video thành các cửa sổ 10 giây (có thể chỉnh qua `VIDEO_ANALYSIS_WINDOW_SECONDS`); mỗi cửa sổ có tối đa 8 frame (qua `VIDEO_ANALYSIS_MAX_FRAMES_PER_WINDOW`). Frame đầu/cuối và các frame có thay đổi hình ảnh lớn được gửi cùng một request sang Cosmos. Vì vậy video 10 giây là một chuỗi, video 1 phút là sáu chuỗi nhỏ có mốc thời gian rõ ràng; không nhồi toàn bộ video vào context của mô hình.

Cosmos chỉ kết luận chuyển động, ngã, giằng co hoặc vật bị bỏ lại khi bằng chứng xuất hiện qua nhiều frame của cùng cửa sổ. Kết quả CameraAI lưu theo từng cửa sổ `[bắt đầu–kết thúc]`, rồi tổng hợp mức rủi ro cao nhất cho báo cáo.

### Gemini: lớp tổng hợp báo cáo cuối

Cosmos chỉ tạo evidence hình ảnh theo từng cửa sổ; Gemini nhận các evidence đó cùng transcript PhoWhisper (nếu đã chạy) để viết kết luận và khuyến nghị hoàn toàn bằng tiếng Việt. Mặc định Gemini **không nhận video/ảnh gốc**, chỉ nhận JSON evidence và transcript nhằm giảm rủi ro lộ dữ liệu camera.

Khai báo key trên máy chạy Web CameraAI, không ghi vào Git hoặc `nvr_config.json`:

```powershell
setx GEMINI_API_KEY "KEY_MOI_CUA_BAN"
setx CAMERAAI_GEMINI_MODEL "gemini-2.0-flash"
```

Mở terminal mới và restart Web CameraAI sau khi đặt biến môi trường. Nếu key không tồn tại hoặc Gemini lỗi, phân tích Cosmos vẫn hoàn tất; hệ thống không làm mất evidence video.

## 10. Các quyết định cần chốt trước khi code

1. NAS là SMB/NFS hay MinIO/S3-compatible? Dung lượng và đường dẫn/prefix được cấp?
2. Cloud dùng nhà cung cấp nào; cần lưu tại khu vực nào; giới hạn ngân sách mỗi tháng?
3. Mỗi loại sự kiện cần giữ bao lâu, ai được xem/tải/xóa?
4. Camera/NVR hiện có trả `source_event_id`, thời gian và channel ổn định đến mức nào?
5. Hệ thống hiện tại có bao nhiêu camera, tổng dung lượng video cũ và các thư mục nguồn chính?
