# Định hướng pilot AI — Phòng Quản lý Học sinh Sinh viên

## Tiến độ triển khai

### Đã hoàn thành

- [x] Đọc và chốt kiến trúc pilot: CV/tracker/rule engine là nguồn dữ kiện; Cosmos chỉ diễn giải event đã xác minh.
- [x] Tạo camera profile YAML mẫu cho một camera pilot, gồm vùng cửa, chờ, bàn trực và các ngưỡng ban đầu.
- [x] Thêm bộ đọc/kiểm tra camera profile: kiểm tra polygon, ID bàn, số nhân sự và các ngưỡng.
- [x] Thêm hàm hình học gán người vào vùng theo điểm chân bounding box.
- [x] Thêm rule engine nền: trạng thái `covered`, `overstaff`, `uncovered_pending`, `uncovered_alert`, cảnh báo đông và chống lặp cảnh báo.
- [x] Khi phát hiện đổi góc camera, trả `needs_recalibration` và tắt rule zone thay vì tạo cảnh báo sai.
- [x] Thêm unit test cho vắng theo ngưỡng, bàn có nhân viên và scene-change (3/3 test đạt).
- [x] Thêm prompt profile `student_affairs` và khai báo phụ thuộc PyYAML.

### Đang thực hiện

- [x] Đổi detector đồng phục từ kết quả đếm tổng sang danh sách person candidate (`bbox`, confidence, yellow score, blue score), vẫn giữ adapter tương thích luồng tuyển sinh cũ.
- [x] Thêm tracker độc lập theo từng camera, giữ `track_id` qua che khuất ngắn.
- [ ] Bổ sung state machine ra/vào cửa: chỉ chuyển `OUTSIDE` khi có chuỗi bằng chứng qua vùng cửa; mất track giữa phòng chỉ ghi `uncertain_lost_track`.
- [ ] Thêm service/endpoint pilot nhận frame, trả JSON contract của rule engine và health/config version.

### Chưa bắt đầu

- [ ] Tích hợp Live: gửi frame 1–2 FPS kèm `camera_id`, `channel`, `captured_at`; giữ `/analyze` cũ không đổi cho profile hiện có.
- [ ] Nối event xác minh với log/replay hiện có; UI chỉ hiển thị event đã xác thực.
- [ ] Chỉ gọi Cosmos khi alert hoặc trạng thái vận hành thay đổi; không gọi trên mọi frame.
- [x] Chạy offline trên video pilot và xuất overlay track ID/zone để hiệu chỉnh.
- [ ] Thêm test đầy đủ cho camera profile, crowding, ra/vào, mất track, quay lại và cảnh báo lặp.
- [ ] Đo hiệu năng GPU/tracker, sau đó mới pin phiên bản runtime phù hợp trong requirements.
- [ ] Đánh giá log so với video thật, chỉnh ngưỡng trước khi cân nhắc fine-tune detector.

### Cần chốt từ phía vận hành trước khi tích hợp Live

- [ ] Camera pilot, mã đầu ghi/kênh và việc camera có nhìn rõ cửa hay không.
- [ ] Số bàn cần trực, thời gian vắng hợp lệ và ngưỡng đông sinh viên/thời lượng xác nhận.
- [ ] Camera có bị xoay hoặc zoom trong ca không; người chịu trách nhiệm xác nhận lại zone sau scene-change.
- [ ] Có được phép dùng audio hay không. Nếu không, không đưa “lớn tiếng” vào alert tự động.

## 1. Mục tiêu và quyết định kiến trúc

Làm đúng **một camera pilot** trước. Camera pilot phải nhìn được tối thiểu:

- các bàn trực;
- khu vực sinh viên chờ/trước bàn;
- cửa ra vào (nếu cần theo dõi nhân viên ra ngoài và thời gian vắng).

Mục tiêu của pilot không phải là trả lời bằng một prompt từ một ảnh. Hệ thống phải theo dõi người qua nhiều frame, lưu trạng thái theo thời gian, sau đó mới tạo cảnh báo và câu báo cáo ngắn.

```
Camera / NetSDK snapshot (1–2 FPS)
        |
        v
YOLO person + áo vàng + tracker theo ID
        |
        v
Vùng chức năng của camera (bàn, chờ, cửa)
        |
        v
Rule engine + trạng thái theo thời gian
        |
        +--> cảnh báo / replay / log có cấu trúc
        |
        +--> prompt chỉ diễn giải dữ kiện đã xác minh
```

Prompt không được dùng để đếm nhân viên, kết luận vắng mặt, hoặc đo thời gian ra ngoài. Prompt chỉ nhận dữ kiện từ rule engine và viết báo cáo tiếng Việt.

## 2. Phạm vi pilot

| Nghiệp vụ | Kết quả pilot cần có | Điều kiện bắt buộc |
| --- | --- | --- |
| Nhân viên trực bàn | Mỗi bàn: có/không có một nhân viên áo vàng trực | Có cấu hình vùng bàn và số bàn cần trực |
| Vắng mặt | Số bàn không có người trực sau một ngưỡng thời gian | Không gọi một frame là vắng mặt |
| Ra ngoài | Thời điểm ra cửa, trở lại, thời lượng tạm vắng | Camera phải nhìn rõ cửa; tracker giữ được ID |
| Sinh viên đông | Số track ID trong vùng chờ/trước bàn và cảnh báo khi vượt ngưỡng | Cấu hình vùng chờ + ngưỡng riêng của phòng |
| Xô xát | Cảnh báo “dấu hiệu xô xát cần kiểm tra” từ nhiều frame | Không kết luận sự việc từ một tư thế đơn lẻ |
| Lớn tiếng | Không triển khai bằng video ở pilot | Cần audio/microphone và một pipeline âm thanh riêng |

Không nhận diện khuôn mặt, tên nhân viên hay danh tính sinh viên. Track ID chỉ tồn tại trong phiên camera và dùng để đo hiện diện/di chuyển.

## 3. Những gì code hiện tại đang làm

| Thành phần hiện tại | File | Hiện trạng | Hạn chế với bài toán mới |
| --- | --- | --- | --- |
| Lấy ảnh Live | `NetSDK_Camera/Demo/RealPlayDemo/RealPlayDemo.py` | Gọi `SnapPictureEx`, mặc định gửi một ảnh mỗi `COSMOS_SAMPLE_INTERVAL_SECONDS=10` giây tới `/analyze` | 10 giây/frame và không có track ID, nên không đo được ra/vào hoặc thời lượng |
| API Live | `cosmos_code_base/live_service.py` | Nhận JPEG đơn, chạy Cosmos VLM; có lock chỉ cho một inference; ghi replay/log | Không có trạng thái người/bàn/cửa theo camera |
| Nhận diện đồng phục | `cosmos_code_base/staff_uniform_detector.py` | YOLO class `person`, cắt thân trên, đếm tỷ lệ HSV vàng/xanh | Đếm độc lập từng frame; nhầm ánh sáng/áo/vật vàng; không biết người nào là cùng một người |
| Prompt profile | `cosmos_code_base/prompts/profiles/*.txt` | Chọn qua `COSMOS_LIVE_PROMPT_PROFILE` | Prompt không thay được detector/tracker/rule thời gian |
| Replay cảnh báo | `live_service.py` + `RealPlayDemo.py` | Lưu khoảng thời gian trước/sau cảnh báo, UI chọn để xem lại | Có thể tái sử dụng khi rule engine phát cảnh báo xác thực |
| Launcher | `NetSDK_Camera/launcher.py` | Đọc `COSMOS_LIVE_URL`, sample interval và prompt profile | Cần thêm cấu hình endpoint/chế độ pilot, không thay logic launch demo |

Kết luận: không cần viết lại ứng dụng NetSDK hay Playback. Cần thay đường phân tích Live từ “ảnh → VLM → câu chữ” thành “frame liên tiếp → CV tracker/rule → sự kiện → câu chữ”.

## 4. Kiến trúc đề xuất cho một camera

### 4.1 Camera profile, không hard-code theo góc quay

Tạo một file cấu hình cho camera pilot. Đây là bước onboarding nhẹ, không phải train lại model cho mỗi camera.

Ví dụ: `cosmos_code_base/configs/cameras/student_affairs_pilot.yaml`

```yaml
camera_id: student-affairs-pilot-01
profile: student_affairs
source_channel: 0

# Tọa độ chuẩn hóa 0.0–1.0 theo kích thước ảnh.
zones:
  entrance: [[0.02, 0.30], [0.16, 0.30], [0.16, 0.95], [0.02, 0.95]]
  waiting: [[0.20, 0.55], [0.82, 0.55], [0.82, 0.98], [0.20, 0.98]]
  desks:
    - id: desk_01
      polygon: [[0.22, 0.10], [0.46, 0.10], [0.46, 0.52], [0.22, 0.52]]
      expected_staff: 1
    - id: desk_02
      polygon: [[0.54, 0.10], [0.80, 0.10], [0.80, 0.52], [0.54, 0.52]]
      expected_staff: 1

thresholds:
  frame_interval_seconds: 1
  absent_after_seconds: 90
  exit_confirm_seconds: 4
  crowd_warn_people: 10
  crowd_confirm_seconds: 20
  scene_change_threshold: 0.35
```

Không dùng rule “nhân viên luôn ngồi sát mép tường” trong code chung. Trong pilot, vùng bàn/cạnh tường là dữ liệu cấu hình của camera. Nếu camera bị quay sang góc khác, hệ thống phải đánh dấu `needs_recalibration`, tắt rule bàn/cửa và không báo vắng sai.

### 4.2 Pipeline CV theo thời gian

1. Lấy frame ở 1–2 FPS từ camera đang xem.
2. YOLO chỉ detect `person`.
3. Classifier áo vàng dùng phần thân trên, nhưng trả về xác suất theo từng track, không chốt từ một frame.
4. Tracker tạo `track_id` riêng cho camera và giữ track qua che khuất ngắn.
5. Mỗi track được gán zone theo điểm chân người (bottom-center của bounding box), không dùng tâm box.
6. State machine cập nhật hiện diện bàn, cửa, hàng chờ và các cảnh báo sau nhiều frame liên tiếp.

Khởi đầu với BoT-SORT có camera-motion compensation; chỉ bật ReID khi dữ liệu pilot chứng minh ID bị đổi nhiều do che khuất. Không dùng một tracker state cho hai camera khác nhau.

### 4.3 State machine cần có

```text
track áo vàng
  UNKNOWN
    -> AT_DESK(desk_id)        khi ở zone bàn đủ số frame xác nhận
    -> EXITING                 khi đi qua entrance theo hướng ra
    -> OUTSIDE                 khi mất track sau khi EXITING đủ ngưỡng
    -> RETURNING / AT_DESK     khi track xuất hiện qua entrance theo hướng vào

desk
  COVERED                      có đúng một track áo vàng ổn định
  UNCOVERED_PENDING            không có người trực, chưa đủ thời gian
  UNCOVERED_ALERT              vượt absent_after_seconds
  OVERSTAFF                    hơn một nhân viên trong cùng vùng bàn
```

Trường hợp tracker mất ID ở giữa ảnh không được chuyển thẳng sang `OUTSIDE`; chỉ ghi `uncertain_lost_track`. Đây là điều kiện để tránh báo sai nhân viên “đi ra ngoài”.

## 5. Danh sách sửa/thêm file

### Sửa các file hiện có

| File | Thay đổi cần làm |
| --- | --- |
| `NetSDK_Camera/Demo/RealPlayDemo/RealPlayDemo.py` | Tách tần suất frame cho tracker khỏi `COSMOS_SAMPLE_INTERVAL_SECONDS`; gửi frame kèm `camera_id`, `channel`, `captured_at` tới endpoint pilot. UI chỉ hiển thị event đã xác thực và replay tương ứng. |
| `cosmos_code_base/live_service.py` | Giữ `/analyze` hiện tại cho profile cũ. Thêm route/service dành cho stateful tracking, hoặc chuyển tiếp sang service mới. Không chạy Cosmos VLM cho mọi frame. |
| `cosmos_code_base/staff_uniform_detector.py` | Đổi API từ tổng `yellow_uniform_staff` sang danh sách person detection: bbox, confidence, yellow score, blue score. Không giữ count như nguồn sự thật. |
| `cosmos_code_base/prompts/PROMPT_PROFILES.md` | Bổ sung `student_affairs` vào danh sách profile và hướng dẫn reload/restart. |
| `cosmos_code_base/prompts/profiles/admissions.txt` | Giữ riêng cho tuyển sinh, không tái sử dụng cho phòng quản lý HSSV. |
| `cosmos_code_base/requirements.txt` | Bổ sung tracker/runtime khi chọn implementation; pin version tương thích GPU sau khi pilot đo được hiệu năng. |

### Thêm các file mới

| File đề xuất | Trách nhiệm |
| --- | --- |
| `cosmos_code_base/configs/cameras/student_affairs_pilot.yaml` | Zones, ngưỡng, số bàn và metadata của camera pilot |
| `cosmos_code_base/student_affairs/config.py` | Đọc/validate YAML; kiểm tra polygon và ngưỡng |
| `cosmos_code_base/student_affairs/detector.py` | Bọc YOLO + classifier áo vàng, trả person candidate có bbox/score |
| `cosmos_code_base/student_affairs/tracker.py` | Một tracker instance cho một camera; quản lý track ID và độ tin cậy |
| `cosmos_code_base/student_affairs/zones.py` | Point-in-polygon, gán zone, phát hiện đi qua cửa theo hướng |
| `cosmos_code_base/student_affairs/rules.py` | State machine bàn trực, vắng mặt, ra/vào, đông sinh viên, chống lặp cảnh báo |
| `cosmos_code_base/student_affairs/state_store.py` | State trong RAM + snapshot JSON định kỳ; không lưu ảnh gốc nếu không cần replay |
| `cosmos_code_base/student_affairs/service.py` | FastAPI endpoint nhận frame và trả event cấu trúc; có health/config version |
| `cosmos_code_base/prompts/profiles/student_affairs.txt` | Prompt chỉ diễn giải event đã xác minh |
| `cosmos_code_base/tests/test_student_affairs_rules.py` | Unit test state machine bằng chuỗi track giả lập |
| `cosmos_code_base/tests/test_student_affairs_camera_profile.py` | Validate config zone và scene-change behavior |

## 6. Contract dữ liệu giữa CV, rule engine và UI

Rule engine trả JSON có cấu trúc; UI không ghép câu từ count thô.

```json
{
  "camera_id": "student-affairs-pilot-01",
  "captured_at": "2026-08-21T10:15:00+07:00",
  "scene_status": "ready",
  "desks": [
    {"id": "desk_01", "status": "covered", "staff_tracks": [17]},
    {"id": "desk_02", "status": "uncovered_alert", "since_seconds": 94}
  ],
  "waiting": {"people": 11, "status": "crowded"},
  "exits": [
    {"track_id": 17, "status": "outside", "since_seconds": 137}
  ],
  "alerts": [
    {
      "id": "desk_02_uncovered",
      "risk_level": "medium",
      "summary": "Bàn trực 02 chưa có nhân viên áo vàng trong hơn 90 giây.",
      "replay_seconds": 30
    }
  ]
}
```

Cosmos chỉ được gọi khi `alerts` hoặc trạng thái vận hành thay đổi. Prompt nhận event facts, ví dụ “Bàn 02 uncovered 94 giây; vùng waiting crowded”, và không được thêm count/duration không có trong facts.

## 7. Prompt profile đề xuất

Tên: `student_affairs`.

Nội dung prompt phải theo hướng:

- Viết tiếng Việt ngắn, chỉ mô tả facts đầu vào từ rule engine.
- Không đếm lại người từ ảnh.
- Không gọi người bị mất track là ra ngoài nếu event không phải `outside`.
- Không khẳng định lớn tiếng; chỉ dùng dữ liệu audio trong tương lai.
- Với xô xát: “có dấu hiệu cần kiểm tra” cho đến khi action model xác nhận.
- Không nhận dạng hoặc suy diễn danh tính.

Ví dụ đầu ra hợp lệ:

```text
Bàn trực 02 chưa có nhân viên áo vàng trong hơn 90 giây. Khu vực chờ đang đông, cần theo dõi thêm.
```

## 8. Kế hoạch triển khai theo thứ tự

1. **Thu thập dữ liệu pilot:** lấy ít nhất một ca có nhân viên trực, đổi ca, nhân viên đi qua cửa, sinh viên đông và khung hình có che khuất.
2. **Onboarding camera:** tạo YAML zone, xác nhận số bàn cần trực, ngưỡng đông và cửa quan sát được.
3. **CV + tracker:** chạy offline trên video pilot, xuất overlay track ID/zone để hiệu chỉnh trước khi kết nối Live.
4. **Rule engine:** unit test các trường hợp vắng, ra ngoài, quay lại, mất track giữa phòng, quá đông và cảnh báo lặp.
5. **Live integration:** gửi 1–2 FPS cho CV tracker; giữ Cosmos ở nhịp thấp và chỉ khi có thay đổi.
6. **Đánh giá:** so đối chiếu log với video thật; chỉnh ngưỡng trước, chỉ fine-tune detector nếu lỗi áo vàng vẫn lặp lại.
7. **Nhân rộng:** chỉ sau khi pilot đạt tiêu chí; tạo camera profile mới thay vì fork code.

## 9. Tiêu chí nghiệm thu pilot

- Không báo “ra ngoài” khi người chỉ bị che khuất hoặc tracker mất ID giữa phòng.
- Không báo vắng khi bàn vẫn có nhân viên áo vàng liên tục trong vùng bàn.
- Cảnh báo bàn không trực chỉ xuất hiện sau ngưỡng cấu hình, không từ một frame.
- Mỗi cảnh báo chỉ tạo một log/replay cho cùng một trạng thái; có thay đổi thực sự mới tạo event mới.
- UI hiện nguồn dữ kiện: camera, bàn, trạng thái, thời gian; không hiện câu VLM tự đếm lại.
- Nếu camera thay đổi góc đáng kể, trạng thái là `needs_recalibration` thay vì tiếp tục áp zones cũ.

## 10. Quyết định cần chốt trước khi code

1. Camera pilot nào, mã đầu ghi/kênh nào, và có nhìn rõ cửa không?
2. Có bao nhiêu bàn cần trực trong ca, và “vắng” sau bao nhiêu giây là hợp lý?
3. Ngưỡng “đông sinh viên” là bao nhiêu người/bao lâu?
4. Camera có hay bị xoay/zoom trong ca không? Nếu có, ai sẽ xác nhận lại zone sau scene-change?
5. Có audio hợp pháp/được phép sử dụng không? Nếu không, bỏ yêu cầu “lớn tiếng” khỏi alert tự động.

## 11. Không làm trong pilot

- Không train lại YOLO trước khi có video lỗi được gắn nhãn.
- Không nhận diện khuôn mặt hoặc liên kết danh tính nhân viên qua nhiều camera.
- Không dùng VLM làm nguồn số liệu người/bàn/thời lượng.
- Không mở rộng đồng thời cho 20 camera hoặc 10 phòng ban.
