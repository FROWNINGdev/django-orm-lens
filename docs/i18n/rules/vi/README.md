# Tài liệu tham khảo quy tắc

Mỗi mã `DOL` là một rule lint mà extension VS Code áp dụng ngay khi bạn gõ code. Các lệnh CLI (`nplusone`, `migration-risk`, `blast-radius`) chạy cùng phân tích đó ở quy mô toàn dự án.

## Quy tắc queryset

| Mã | Tiêu đề | Mức độ | Khả năng áp dụng |
|----|---------|--------|------------------|
| [DOL001](DOL001.md) | Ưu tiên `.exists()` thay vì `.count() > 0` | info | safe |
| [DOL002](DOL002.md) | Ưu tiên `.count()` thay vì `len(queryset)` | info | safe |
| [DOL003](DOL003.md) | Tránh `list(queryset)` trong ngữ cảnh boolean | info | safe |
| [DOL004](DOL004.md) | Dùng `.only()` / `.defer()` để giới hạn trường được tải | info | unsafe |
| [DOL005](DOL005.md) | Tránh gọi `.all()` trước `.filter()` | info | safe |
| [DOL006](DOL006.md) | Dùng `.iterator()` cho queryset lớn | warning | unsafe |
| [DOL007](DOL007.md) | Có thể xảy ra N+1: truy cập thuộc tính bên trong vòng lặp for | warning | unsafe |
| [DOL008](DOL008.md) | Dùng `flat=True` khi gọi `.values_list()` với một trường duy nhất | info | safe |

## Quy tắc định nghĩa model

| Mã | Tiêu đề | Mức độ | Khả năng áp dụng |
|----|---------|--------|------------------|
| [DOL011](DOL011.md) | Thêm `db_index=True` cho trường FK dùng trong filter | warning | unsafe |
| [DOL012](DOL012.md) | Thêm `db_index=True` cho trường dùng trong `order_by()` | info | unsafe |
| [DOL013](DOL013.md) | Dùng `select_related` cho các truy cập FK trong serializer | warning | unsafe |
| [DOL014](DOL014.md) | Dùng `prefetch_related` cho các truy cập FK ngược / M2M | warning | unsafe |
| [DOL015](DOL015.md) | Tránh lưu dữ liệu lớn trực tiếp trên model | info | unsafe |

## Quy tắc datetime

| Mã | Tiêu đề | Mức độ | Khả năng áp dụng |
|----|---------|--------|------------------|
| [DOL021](DOL021.md) | Dùng `timezone.now()` thay vì `datetime.now()` | warning | safe |
| [DOL022](DOL022.md) | Dùng `timezone.now()` để so sánh với `DateTimeField` | warning | safe |

## Quy tắc forms / views

| Mã | Tiêu đề | Mức độ | Khả năng áp dụng |
|----|---------|--------|------------------|
| [DOL031](DOL031.md) | Dùng `get_object_or_404()` thay vì `.get()` trực tiếp | info | safe |
| [DOL032](DOL032.md) | Tránh truyền dữ liệu request thô vào queryset | warning | unsafe |

## Công cụ phân tích CLI

| Lệnh | Chức năng |
|------|-----------|
| [nplusone](nplusone.md) | Phát hiện các pattern N+1 trên toàn dự án |
| [migration-risk](migrations.md) | Đánh giá file migration theo 16 quy tắc an toàn |
| [blast-radius](blast-radius.md) | Kết hợp migration risk với phân tích tham chiếu toàn codebase |
| [drift](drift.md) | Phát hiện khi `db_table` hoặc tên cột lệch khỏi convention Django |
