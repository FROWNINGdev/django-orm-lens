# migration-risk

Lệnh `migration-risk` chấm điểm mọi file migration trong dự án của bạn dựa trên 16 rule và báo cáo những file mang rủi ro production. Nó được thiết kế để chạy trong CI để các migration nguy hiểm bị bắt lại trước khi chúng đến tay deploy.

## Nó kiểm tra gì

| Mã (Code) | Rủi ro (Risk) | Mức độ mặc định |
|-----------|---------------|-----------------|
| `add_column_with_default` | Thêm cột với default khác null sẽ viết lại (rewrite) bảng trên Postgres cũ | warning |
| `add_not_null_column` | Thêm cột NOT NULL không có default yêu cầu viết lại toàn bộ bảng | error |
| `alter_column_type` | Thay đổi kiểu cột sẽ lock bảng trong khi cột được viết lại | error |
| `drop_column` | Xóa cột là hành động không thể đảo ngược và có thể làm hỏng code vẫn đang đọc nó | error |
| `drop_table` | Xóa bảng là hành động không thể đảo ngược | error |
| `rename_column` | Đổi tên cột làm hỏng mọi code tham chiếu đến tên cũ | error |
| `rename_table` | Đổi tên bảng làm hỏng mọi code tham chiếu đến tên cũ | error |
| `create_index` | Tạo index mà không có `CONCURRENTLY` sẽ lock bảng | warning |
| `drop_index` | Xóa index có thể làm giảm hiệu suất query | warning |
| `add_unique_constraint` | Thêm unique constraint yêu cầu quét toàn bộ bảng | warning |
| `drop_unique_constraint` | Xóa unique constraint có thể cho phép trùng lặp dữ liệu | warning |
| `add_check_constraint` | Thêm check constraint yêu cầu quét toàn bộ bảng | warning |
| `drop_check_constraint` | Xóa check constraint có thể cho phép dữ liệu không hợp lệ | warning |
| `raw_sql` | Raw SQL trong migration là hộp đen đối với phân tích tĩnh | warning |
| `remove_field_still_referenced` | Một field bị xóa bởi migration vẫn được tham chiếu trong codebase | error |
| `squash_migration` | Các migration được gộp (squashed) giấu đi lịch sử và có thể làm hỏng rollback | info |

## Cách dùng

```bash
django-orm-lens migration-risk --path .              # toàn bộ dự án
django-orm-lens migration-risk --path apps/blog/migrations
django-orm-lens migration-risk --format json         # định dạng máy đọc được
django-orm-lens migration-risk --format github       # GitHub PR annotations
django-orm-lens migration-risk --severity error      # chỉ các lỗi
```

- **`--path PATH`** — thư mục gốc để quét (mặc định: thư mục hiện tại).
- **`--format text|json|github|markdown`** (mặc định `text`).
- **`--severity info|warning|error`** (mặc định `info`) — mức độ tối thiểu để báo cáo.
- **`--only MIGRATION`** — giới hạn chỉ quét các file này; lặp lại flag cho mỗi file.
- **`--exit-zero`** — luôn thoát với mã `0`.
- **Mã thoát (Exit code)** — `1` khi có finding ở mức hoặc trên ngưỡng severity, `0` trong các trường hợp khác.

## Trong CI

```yaml
- uses: FROWNINGdev/django-orm-lens@action-v1
  with:
    command: migration-risk
    format: github
    severity: warning
```

Mỗi finding trở thành một PR annotation trỏ đúng vào dòng migration tạo ra nó.

## Ghi chú về các rule

### add_column_with_default

PostgreSQL 11+ viết lại các cột có default biến đổi (volatile default) một cách lười biếng (lazily) — cảnh báo "viết lại toàn bộ bảng" cũ không còn áp dụng. Nếu mục tiêu của bạn là Postgres 11+, finding này là false positive và bạn có thể suppress nó. Với Postgres 10 trở xuống, hoặc các backend không phải Postgres, quá trình viết lại vẫn xảy ra.

### add_not_null_column

Pattern an toàn là: thêm cột nullable → backfill dữ liệu → thêm ràng buộc NOT NULL. `AddField` của Django với `default` trên Postgres 11+ là an toàn mà không cần cách làm phức tạp này, nhưng chỉ khi bạn cũng thiết lập `db_default` thay vì default phía Python, cái không thể tồn tại sau một lệnh `migrate` sạch.

### alter_column_type

Dùng pattern ba bước: thêm cột mới, ghi song song (dual-write), backfill dữ liệu, rồi hoán đổi (swap). `SeparateDatabaseAndState` có thể ẩn các bước trung gian khỏi state migration của Django.

### create_index

Luôn dùng `AddIndex` với `condition` hoặc viết SQL trực tiếp là `CREATE INDEX CONCURRENTLY`. Cách sau yêu cầu một transaction riêng biệt và không thể nằm trong `RunSQL` có chứa các công việc khác.

### remove_field_still_referenced

Rule này đối chiếu chéo migration với codebase hiện tại. Nó tìm field bị xóa, sau đó tìm kiếm trong các serializer, view, template, admin, form và method của model xem có bất kỳ tham chiếu nào đến tên field đó trên model đó không. Các mức độ tự tin tuân theo cùng hệ thống phân cấp `certain` / `likely` / `possibly` như lệnh `blast-radius`.

## Cấu trúc JSON

```jsonc
{
  "findings": [
    {
      "migration": "blog/migrations/0002_drop_author.py",
      "line": 7,
      "code": "remove_field_still_referenced",
      "severity": "error",
      "message": "Removes field 'author' from 'post' …",
      "fix": "Confirm no code path still reads/writes the field …"
    }
  ],
  "summary": { "total": 1, "errors": 1, "warnings": 0, "info": 0 }
}
```

## Liên quan

- [`blast-radius`](blast-radius.md) — kết hợp rủi ro migration với tác động từ các tham chiếu
- [`nplusone`](nplusone.md) — phát hiện query N+1
