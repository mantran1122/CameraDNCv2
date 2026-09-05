# Danh sách rà soát dọn code — chưa xóa gì

Ngày rà soát: 2026-08-31. Mục tiêu hiện tại là Dashboard metadata camera + clip 10 giây + Cosmos + AI ngôn ngữ, đồng thời vẫn giữ giao diện phân tích video cũ.

> Quy tắc: chỉ xóa sau khi đã đọc mục tương ứng và chạy lại app. Không xóa theo kiểu `git clean` hoặc xóa cả thư mục lớn ngay.

## A. Có thể bỏ khỏi Git/repo ngay sau khi tự kiểm tra

| Mục | Lý do | Cách xử lý đề nghị |
|---|---|---|
| `NetSDK_Camera.rar` | File nén untracked, có vẻ là bản đóng gói/trùng với thư mục `NetSDK_Camera/`; không nên đưa lên Git. | Xóa file nén nếu đã giải nén và không cần bản backup; hoặc chuyển ra thư mục backup ngoài repo. |
| `.omo/` | Dữ liệu runtime untracked của công cụ, không thuộc source dự án. | Xóa hoặc thêm vào `.gitignore`. |
| `netSDK2/**/build/` | Artifact build CMake/Qt: object file, cache, executable, log, translation copy. Có thể build lại. | Xóa các thư mục `build/`, thêm vào `.gitignore`. |
| `netSDK2/DahuaNCTManager/logs/` | Log sinh ra khi chạy. | Xóa log, ignore thư mục log. |
| `__pycache__/`, `.pytest_cache/`, `outputs/` (trừ `.keep`), `inprogress/`, `queues/`, `playback_inbox/` | Cache, clip/video tải về, kết quả runtime; không phải source. | Xóa dữ liệu cũ khi không cần, giữ file `.keep`/`.gitkeep`, ignore phần còn lại. |

## B. Nên tách/archive khỏi repo chính, không xóa vội

| Mục | Nhận định | Khi nào được archive/xóa khỏi repo app |
|---|---|---|
| `netSDK2/` | Có khoảng 1.281 file, chủ yếu là C++ SDK, header, DLL, tài liệu và demo chính thức của Dahua. App Python hiện dùng `NetSDK_Camera/NetSDK`, không thấy launcher Python import code C++ trong `netSDK2`. | Sau khi xác nhận `NetSDK_Camera` chạy độc lập và đã giữ lại SDK binary/tài liệu cần thiết ở nơi khác. Tốt nhất archive thành repo/thư mục `vendor/dahua-sdk-reference`, không để lẫn vào app. |
| `cloud_ai_first/` | Một frontend/framework khác, không thuộc hướng Dashboard Streamlit/PyQt đang chạy. | Archive nếu không còn ai chạy nó và không phải giao diện đích. |
| Tài liệu SDK trong `netSDK2/Doc/` và `NetSDK_Camera/doc/` | Có thể hữu ích lúc tra API lịch sử metadata, nhưng làm repo nặng và nhiễu. | Giữ một bộ tài liệu đúng SDK/firmware đang dùng; archive phần còn lại. |

## C. Cần quyết định sản phẩm trước khi xóa

Các demo dưới đây đang được `NetSDK_Camera/launcher.py` đăng ký trong launcher. Vì vậy xóa file là launcher sẽ lỗi trừ khi sửa danh sách demo trước.

| Demo Python | Giữ nếu cần | Có thể bỏ nếu không thuộc sản phẩm |
|---|---|---|
| `Demo/AlarmListen/` | Cần nhận alarm cơ bản; tham khảo callback event | Bỏ nếu adapter metadata mới thay hoàn toàn demo này |
| `Demo/PlayBackDemo/` | Cần tải đoạn 10 giây từ NVR qua `DownloadByTimeEx` | Không nên bỏ lúc này |
| `Demo/RealPlayDemo/` | Cần xem live camera | Bỏ nếu Dashboard không cần live view |
| `Demo/SearchDeviceDemo/` | Cần quét/tìm camera trong LAN | Bỏ nếu camera cấu hình thủ công |
| `Demo/DeviceControlDemo/` | Cần điều khiển/cấu hình thiết bị | Bỏ nếu dự án chỉ đọc dữ liệu NVR |
| `Demo/CapturePicture/` | Cần chụp snapshot thủ công | Bỏ nếu không dùng snapshot |
| `Demo/FaceRecognitionDemo/` | Cần màn demo face SDK độc lập | Có thể bỏ; Dashboard sẽ đọc metadata camera thay vì dùng demo UI này |
| `Demo/IntelligentTrafficDemo/` | Cần demo giao thông | Có thể bỏ nếu không làm giao thông |
| `Demo/VideoToTextDemo/` | Cần giao diện PyQt audio-to-text riêng | Cân nhắc bỏ/sáp nhập vì Cosmos đã có `app/audio_to_text_demo.py` |

## D. Phần Cosmos: nên hợp nhất dần, chưa xóa ngay

| Vùng | Vấn đề | Hướng hợp lý |
|---|---|---|
| `NetSDK_Camera/Demo/VideoToTextDemo/`, `cosmos_code_base/audio_to_text.py`, `cosmos_code_base/app/audio_to_text_demo.py` | Ba lớp/điểm vào liên quan video/audio-to-text. | Chọn `audio_to_text.py` làm service/core; chọn **một** UI chính (Dashboard/Streamlit hoặc PyQt) rồi bỏ UI còn lại sau khi thay thế. |
| `cosmos_code_base/app/streamlit_app.py` | Đây là giao diện phân tích video cũ mà yêu cầu mới nói phải giữ. | Giữ nguyên; sau này chỉ bọc vào tab `Phân tích Video`. |
| `cosmos_code_base/student_affairs/` + `configs/cameras/student_affairs_pilot.yaml` + `STUDENT_AFFAIRS_*` | Một hướng nghiệp vụ riêng (theo dõi sinh viên) song song với hướng metadata camera tổng quát. | Giữ nếu vẫn là pilot cần làm. Nếu đã đổi hẳn sang Dashboard metadata tổng quát, archive cả cụm cùng nhau; không xóa từng file lẻ. |
| `LIVE_ADMISSIONS_MONITORING_SPEC.md`, profile prompt `admissions.txt`, `live_admissions_prompt.txt` | Hướng admissions/live cũ, có khả năng trùng/không còn mục tiêu chính. | Chọn một prompt profile mặc định; archive các spec/profile không dùng. |
| `UI_REDESIGN_PLAN.md`, `UI_CONTENT_SPEC.md` | Đặc tả UI cũ, trước Dashboard metadata mới. | Giữ làm lịch sử tạm thời; sau khi UI mới được duyệt, gộp nội dung còn giá trị vào một spec và archive hai file cũ. |
| `PLAYBACK_AI_INTEGRATION_PLAN.md`, `CAMERA_COSMOS_INTEGRATION_PLAN.md`, `CAMERA_METADATA_PIPELINE_DIRECTION.md` | Nhiều tài liệu định hướng cùng chủ đề. | Dùng `CAMERA_METADATA_PIPELINE_DIRECTION.md` làm hướng hiện hành; đọc hai plan cũ để chuyển các ý còn cần, sau đó archive chúng. |

## E. Cấu trúc đích nên giữ gọn

```text
CameraDNC/
├── NetSDK_Camera/                 # chỉ code Python/SDK cần chạy và demo được chọn
├── cosmos_code_base/              # dashboard mới + tab phân tích video cũ + pipeline AI
├── docs/                           # tài liệu định hướng đang hiệu lực
├── vendor/                         # chỉ SDK/tài liệu Dahua thật sự cần, nếu cần giữ
├── .gitignore
└── README.md                       # một điểm vào chính
```

Không để `build/`, log, video tải về, model cache, archive `.rar`, hay full sample SDK lẫn với source app.

## F. Trình tự dọn an toàn

1. Đọc mục A, xóa/ignore artifact và file nén trước; không ảnh hưởng code.
2. Chốt danh sách demo NetSDK cần giữ cho sản phẩm.
3. Sửa `launcher.py` để chỉ hiển thị demo đã chọn, rồi chạy thử launcher.
4. Chốt UI chính cho audio-to-text và archive UI trùng.
5. Chốt giữ hay archive toàn bộ `student_affairs/` như một feature độc lập.
6. Gộp các tài liệu kế hoạch cũ vào các file direction hiện hành.
7. Cuối cùng mới chuyển `netSDK2/` và `cloud_ai_first/` ra archive/repo khác.

## G. Những thứ không nên xóa lúc này

- `NetSDK_Camera/NetSDK/`: wrapper Python hiện dùng để login, nghe event và tải replay.
- `NetSDK_Camera/Demo/PlayBackDemo/`: đang là ví dụ có sẵn cho luồng tải video theo thời gian.
- `cosmos_code_base/src/`, `main.py`, `live_service.py`: lõi phân tích video/live hiện có.
- `cosmos_code_base/app/streamlit_app.py`: giao diện cũ phải giữ theo yêu cầu.
- `CAMERA_METADATA_PIPELINE_DIRECTION.md` và `CAMERA_METADATA_DASHBOARD_UI_DIRECTION.md`: hướng hiện hành cho chức năng mới.

