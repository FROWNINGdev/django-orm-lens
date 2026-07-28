# Tài liệu Quy tắc

Mỗi trang dưới đây mô tả một quy tắc cụ thể: mã quy tắc, độ nghiêm trọng mặc định, khả năng áp dụng, các ví dụ về code sai/đúng, và cách bỏ qua (suppress) nếu cần.

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

## Định nghĩa Model

| Mã | Tóm tắt | Mức độ | Áp dụng |
|----|---------|--------|---------|
| [DOL011](DOL011.md) | Thêm `db_index=True` cho các trường ForeignKey được lọc thường xuyên | hint | suggestion |
| [DOL012](DOL012.md) | `null=True` trên trường chuỗi — dùng chuỗi rỗng thay thế | info | suggestion |
| [DOL013](DOL013.md) | Thiếu `related_name` trên ForeignKey | hint | suggestion |
| [DOL014](DOL014.md) | Dùng `get_or_create()` thay vì `try/except` bọc `.get()` | info | safe |
| [DOL015](DOL015.md) | `ManyToManyField` không có `through=` có thể nên khai báo tường minh | hint | suggestion |

## Ngày giờ (Datetime)

| Mã | Tóm tắt | Mức độ | Áp dụng |
|----|---------|--------|---------|
| [DOL021](DOL021.md) | Dùng `timezone.now()` thay vì `datetime.now()` | warning | safe |
| [DOL022](DOL022.md) | Dùng `timezone.now()` thay vì `datetime.utcnow()` | warning | safe |

## Forms / Views

| Mã | Tóm tắt | Mức độ | Áp dụng |
|----|---------|--------|---------|
| [DOL031](DOL031.md) | Không gọi `form.save()` sau khi `form.is_valid()` trả về `False` | error | safe |
| [DOL032](DOL032.md) | Luôn gọi `form.is_valid()` trước `form.save()` | error | safe |

## Tài liệu bổ sung

- [Vấn đề N+1 và cách phân tích](nplusone.md)
- [Quy tắc liên quan đến Migration](migrations.md)

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
