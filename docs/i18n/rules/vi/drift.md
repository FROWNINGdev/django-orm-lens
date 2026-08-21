# drift

Lệnh `drift` phát hiện khi các định danh cơ sở dữ liệu của model bạn — tên bảng và tên cột — sai lệch so với những gì Django tạo ra theo mặc định. Nó không kết nối với database; nó so sánh `Meta.db_table`, `Field.db_column`, và `Field.column` với cái tên mà Django tự suy ra từ app label và tên field.

## Nó phát hiện gì

- `Meta.db_table` khác với `<app_label>_<model_name_lower>`
- `db_column` khác với tên trường (viết thường)
- Override `Field.column` sai lệch với mặc định của Django

Sự sai lệch (drift) không phải lúc nào cũng sai — một tên bảng legacy là một lựa chọn có chủ ý — nhưng sai lệch không được ghi nhận (undocumented) là một mối nguy hiểm cho bảo trì. Công cụ báo cáo nó để bạn có thể xác nhận đó là cố ý và, tùy chọn, bỏ qua nó.

## Cách dùng

```bash
django-orm-lens drift --path .                    # toàn bộ dự án
django-orm-lens drift --path apps/blog            # một app cụ thể
django-orm-lens drift --format json              # định dạng máy đọc được
django-orm-lens drift --format github            # GitHub PR annotations
```

- **`--path PATH`** — thư mục gốc để quét (mặc định: thư mục hiện tại).
- **`--format text|json|github|markdown`** (mặc định `text`).
- **`--exit-zero`** — luôn thoát với mã `0`.

## Ví dụ đầu ra

```
blog.Post — db_table: "legacy_posts" (mong đợi "blog_post")
blog.Post.author_id — db_column: "author" (mong đợi "author_id")
```

## Bỏ qua (Suppress)

Đối với sai lệch có chủ ý, thêm một comment trên cùng dòng với khai báo `db_table` hoặc `db_column`:

```python
class Post(models.Model):
    class Meta:
        db_table = "legacy_posts"  # django-orm-lens-disable drift
```

## Liên quan

- [`migration-risk`](migrations.md)
- [`blast-radius`](blast-radius.md)
