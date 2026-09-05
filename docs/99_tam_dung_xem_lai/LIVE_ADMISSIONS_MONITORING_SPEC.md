# Giám sát khu tuyển sinh — Live Camera AI

## Mục tiêu

Giám sát vận hành khu tuyển sinh bằng camera. Hệ thống nhận biết **người mặc áo vàng (nghi là nhân viên)** và chỉ báo các tình huống cần điều phối hoặc xem lại. Không nhận dạng danh tính, không suy đoán năng suất, ý định hoặc lỗi cá nhân.

## Khu vực quan sát

| Mã | Khu vực | Dấu hiệu cần theo dõi |
| --- | --- | --- |
| `reception` | Quầy tiếp nhận | Nhân viên trực, người chờ, quầy có người chờ nhưng không thấy nhân viên áo vàng |
| `enrollment` | Bàn nhập học | Nhân viên xử lý hồ sơ, trao đổi tại bàn, bàn có khách nhưng thiếu nhân viên |
| `consultation` | Bàn tư vấn | Nhân viên tư vấn, nhóm khách chờ, quá tải cục bộ |
| `waiting` | Khu chờ | Mật độ người chờ, chen lấn, ngã, đồ vật bỏ quên |
| `walkway` | Lối đi | Lối đi thông thoáng, vật cản, tụ tập che lối, ngã, khói/lửa |

Phân vùng trên ảnh hiện tại là sơ bộ: cụm bàn trái, giữa và phải sẽ được gán chính xác cho ba khu bàn khi có tọa độ zone trong camera.

## Trạng thái quan sát

- Nhân viên áo vàng: đang hỗ trợ, xử lý hồ sơ, trao đổi, đứng/chờ, di chuyển, dùng điện thoại khi thấy rõ.
- Khu vực: bình thường, đông người chờ, thiếu nhân viên, lối đi bị cản.
- Sự kiện an toàn/an ninh: ngã, tranh cãi/ẩu đả, khói/lửa, vật bỏ quên, xâm nhập vùng hạn chế.

## Quy tắc cảnh báo

| Mức | Điều kiện quan sát được |
| --- | --- |
| `none` | Hoạt động bình thường, không có dấu hiệu cần xử lý |
| `low` | Khu chờ đông nhẹ hoặc có người di chuyển nhiều nhưng lối đi vẫn thông |
| `medium` | Có người chờ trong một khu bàn nhưng không thấy nhân viên áo vàng; dùng điện thoại rõ ràng tại vị trí trực; lối đi bị tụ tập/cản trở |
| `high` | Ngã, ẩu đả, khói/lửa, nguy cơ an toàn tức thời, lối thoát bị chặn rõ ràng |

Một cảnh báo vận hành chỉ nên được hiển thị sau nhiều lượt phân tích liên tiếp. Một frame chỉ là bằng chứng tức thời, không đủ để khẳng định thời lượng hoặc trách nhiệm cá nhân.

## Đầu ra Live mong muốn

Ưu tiên thông tin điều phối, không mô tả dài về kiến trúc hoặc trang trí:

```text
Nhân viên áo vàng: 11; đang hỗ trợ/xử lý: 8; đang di chuyển: 2.
Quầy tiếp nhận: có 4 người chờ, vẫn thấy nhân viên trực.
Khu chờ và lối đi: thông thoáng.
Cảnh báo: không có.
```

## Giới hạn

- Áo vàng chỉ là dấu hiệu thị giác của đồng phục; ảnh tối, xa hoặc che khuất phải ghi nhận mức không chắc chắn.
- Không nhận dạng khuôn mặt hay gán danh tính.
- Không kết luận hành vi vi phạm nếu không có bằng chứng rõ từ hình ảnh.
