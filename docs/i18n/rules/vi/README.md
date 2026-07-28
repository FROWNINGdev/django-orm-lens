# Tài liệu Quy tắc

Mỗi trang dưới đây mô tả một quy tắc cụ thể (hiện tại danh mục chứa 7 quy tắc): mã quy tắc, độ nghiêm trọng mặc định, khả năng áp dụng, các ví dụ về code sai/đúng, và cách bỏ qua (suppress) nếu cần.

## Queryset

| Mã | Tóm tắt | Mức độ | Áp dụng |
|----|---------|--------|---------|
| [DOL001](DOL001.md) | Ưu tiên `.exists()` thay vì `.count() > 0` | info | safe |
| [DOL002](DOL002.md) | Ưu tiên `not .exists()` thay vì `.count() == 0` | info | safe |
| [DOL003](DOL003.md) | Ưu tiên `not .exists()` thay vì `.first() is None` | info | safe |
| [DOL004](DOL004.md) | Ưu tiên `.exists()` thay vì `.first() is not None` | info | safe |
| [DOL005](DOL005.md) | Cân nhắc dùng `Q(...)` thay vì chuỗi `.filter().exclude()` | hint | suggestion |
| [DOL006](DOL006.md) | Bỏ `list()` bọc ngoài QuerySet trong vòng lặp for | info | safe |
| [DOL007](DOL007.md) | Có thể xảy ra N+1: truy cập thuộc tính bên trong vòng lặp for | warning | unsafe |

## Mức độ nghiêm trọng

| Từ khóa | Ý nghĩa |
|---------|----------|
| `error` | Luôn sai; ưu tiên sửa ngay |
| `warning` | Rất có thể sai; cần xem xét |
| `info` | Viết lại an toàn nhưng không bắt buộc |
| `hint` | Gợi ý cải thiện; cần đánh giá từng trường hợp |

## Khả năng áp dụng

| Từ khóa | Ý nghĩa |
|---------|----------|
| `safe` | QuickFix có thể áp dụng tự động |
| `suggestion` | Cần kiểm tra trước khi áp dụng |
| `unsafe` | Không có QuickFix; phải sửa thủ công |
