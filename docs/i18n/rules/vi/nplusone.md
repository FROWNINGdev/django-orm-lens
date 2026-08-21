# nplusone

Lệnh `nplusone` phát hiện các pattern query N+1 bằng cách phân tích tĩnh (static) các lời gọi ORM trong dự án của bạn — không cần server, không cần test database, không cần instrumented HTTP client. Phân tích này chạy trực tiếp trên các file mã nguồn bạn chỉ định.

## Nó phát hiện gì

Nó đọc mọi vòng lặp `for` có iterable là một biểu thức queryset, sau đó kiểm tra thân vòng lặp để tìm các truy cập thuộc tính có thể kích hoạt lazy load:

- Truy cập `ForeignKey` / `OneToOneField` mà không có `select_related`
- Truy cập ngược `ForeignKey` / `ManyToManyField` mà không có `prefetch_related`
- Truy cập `.values()` / `.values_list()` bên trong vòng lặp nơi trường đó không được bao gồm trong lời gọi ban đầu

Các finding sẽ liệt kê vị trí vòng lặp, thuộc tính được truy cập, và đề xuất cách sửa.

## Cách dùng

```bash
django-orm-lens nplusone --path .                    # toàn bộ dự án
django-orm-lens nplusone --path apps/blog            # một app cụ thể
django-orm-lens nplusone --format json               # định dạng máy đọc được
django-orm-lens nplusone --format github             # GitHub PR annotations
django-orm-lens nplusone --severity warning          # chỉ báo cáo từ mức warning trở lên
```

- **`--path PATH`** — thư mục gốc để quét (mặc định: thư mục hiện tại).
- **`--format text|json|github|markdown`** (mặc định `text`) — định dạng đầu ra.
- **`--severity info|warning|error`** (mặc định `info`) — mức độ tối thiểu để báo cáo.
- **`--exit-zero`** — luôn thoát với mã `0`, hữu ích khi đang xử lý dần nợ kỹ thuật cũ.
- **Mã thoát (Exit code)** — `1` khi có finding ở mức hoặc trên ngưỡng severity, `0` trong các trường hợp khác.

## Trong CI

```yaml
- uses: FROWNINGdev/django-orm-lens@action-v1
  with:
    command: nplusone
    format: github
```

Các annotation trỏ chính xác vào dòng vòng lặp và gọi tên thuộc tính, giúp reviewer thấy vấn đề mà không cần mở tab thứ hai.

## Hạn chế

Phân tích tĩnh không có type inference đồng nghĩa với việc công cụ không thể phân biệt một `ForeignKey` với một thuộc tính thông thường tại nơi gọi — xem thêm lưu ý ở DOL007 về hạn chế tương tự. Bạn có thể bỏ qua (suppress) các false positive bằng comment inline hoặc setting của workspace. Công cụ không bao giờ chạy query thực; để phát hiện ở runtime, hãy dùng kết hợp với package Python `nplusone`.

## Liên quan

- [DOL007](rules/DOL007.md) — rule VS Code kích hoạt trên cùng pattern
- [`blast-radius`](blast-radius.md) — phân tích tác động cho thay đổi schema
- [`migration-risk`](migrations.md) — các rule an toàn cho migration
