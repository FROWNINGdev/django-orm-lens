# blast-radius

Lệnh `blast-radius` kết hợp chấm điểm rủi ro migration với quét tham chiếu toàn codebase. Đối với mỗi hoạt động migration có tính phá hủy (destructive) — `RemoveField`, `RemoveIndex`, `DeleteModel`, `RenameField`, `AlterField` — nó đặt câu hỏi: *có bao nhiêu nơi trong codebase vẫn tham chiếu đến thứ mà migration này xóa hoặc thay đổi?* Câu trả lời chính là bán kính ảnh hưởng (blast radius).

## Nó báo cáo gì

Đối với mỗi đối tượng mục tiêu (field, model, hoặc index bị thay đổi):

- **Rủi ro migration** từ `migration-risk` (rule nào bị vi phạm và ở mức độ nào)
- **Số lượng tham chiếu** được phân chia theo mức độ tự tin và theo tầng kiến trúc của Django (views, serializers, templates, admin, forms, model methods)
- **Xem trước phân tầng (Cascade preview)** — nếu hoạt động là `RemoveField` trên một trường có `on_delete=CASCADE`, công cụ sẽ thực hiện lần phân tích thứ hai để liệt kê mọi model sẽ bị xóa theo dạng cascade

Các mục tiêu được sắp xếp theo mức độ nghiêm trọng từ cao đến thấp, sau đó theo số lượng tham chiếu `certain` còn sót lại, rồi theo tên — vì vậy thứ có khả năng làm hỏng production cao nhất sẽ nằm ở đầu kết quả đầu ra.

## Độ tự tin (Confidence), và tại sao tồn tại mức `possibly`

Các finding tham chiếu có các mức độ `certain` (chắc chắn) / `likely` (có khả năng) / `possibly` (có thể), đến từ cùng một bộ phân loại (classifier) mà extension VS Code sử dụng:

- **certain** — một tham chiếu ORM rõ ràng không thể nhầm lẫn: `filter(author__id=1)`, `order_by("-author")`, `fields = ["author"]`, `list_display`, `search_fields`.
- **likely** — truy cập thuộc tính bên trong một tầng được nhận dạng của Django, hoặc một biến template `{{ post.author }}`.
- **possibly** — một kết quả khớp định danh trần, hoặc truy cập thuộc tính trong một file mà không thể xác định được tầng kiến trúc.

Không có type inference (suy diễn kiểu) ở đây. Đó là công việc của Pyright, và Pyright vốn đã chịu thua trên bề mặt các chuỗi của Django như `ForeignKey` / `related_name` / template. Việc hiển thị tường minh một mức độ `possibly` là sự lựa chọn trung thực thay vì âm thầm loại bỏ những dòng đó.

Bản thân nơi khai báo sẽ không bị đếm — một field không báo cáo khai báo của chính nó như là một ảnh hưởng.

## Cách dùng

```bash
django-orm-lens blast-radius --path .                     # chỉ rủi ro mức critical
django-orm-lens blast-radius --severity all               # mọi thứ
django-orm-lens blast-radius --format markdown            # dùng làm PR-comment body
django-orm-lens blast-radius --format github              # GitHub PR annotations
django-orm-lens blast-radius --format json                # định dạng máy đọc được
django-orm-lens blast-radius --no-cascade                 # bỏ qua phân tích cascade bổ sung
django-orm-lens blast-radius --only blog/migrations/0002_drop_author.py
```

- **`--severity critical|warning|info|all`** (mặc định `critical`) — rủi ro tối thiểu, tương tự `migration-risk`.
- **`--only MIGRATION`** — giới hạn ở các file migration này; lặp lại cờ (flag) cho mỗi file. Truyền vào các đường dẫn thay đổi của một PR để giới hạn báo cáo trong phần diff. Mặc định quét mọi migration trong workspace.
- **`--no-cascade`** — bỏ qua xem trước cascade và bước phân tích workspace bổ sung mà nó cần. Cascade chỉ luôn áp dụng cho các hoạt động cấp độ model.
- **Mã thoát (Exit code)** — `1` khi còn rủi ro critical, `0` nếu không còn. `--exit-zero` luôn thoát bằng mã `0`, hữu ích khi bạn đang từ từ sửa dứt điểm các khoản nợ kỹ thuật cũ.

## Trong CI

Là một GitHub Action, các finding sẽ trở thành các PR annotation mà không yêu cầu thêm quyền (permissions) nào:

```yaml
- uses: FROWNINGdev/django-orm-lens@action-v1
  with:
    command: blast-radius
    format: github
```

Các annotation sẽ trỏ thẳng vào **dòng trong migration** — dòng mã mà người duyệt có thể thao tác — và nêu rõ số lượng tham chiếu trong tiêu đề, để thấy rõ hậu quả mà không cần mở tab thứ hai:

```
::error file=blog/migrations/0002_drop_author.py,line=7,title=django-orm-lens: remove_field_still_referenced (2 certain reference(s))::…
```

### Dùng làm PR comment

`comment: true` sẽ gửi báo cáo dưới dạng markdown và **cập nhật chính comment đó** trong các lần push tiếp theo, do vậy một PR với hai mươi lần push sẽ chỉ chứa một báo cáo thay vì hai mươi cái. `only-changed: true` thu hẹp báo cáo vào các migration mà PR này thực sự chạm tới, và thoát sớm (exit early) khi PR không sửa migration nào.

```yaml
name: Schema review
on: pull_request

permissions:
  contents: read
  pull-requests: write        # chỉ cần thiết cho `comment: true`

jobs:
  blast-radius:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: FROWNINGdev/django-orm-lens@action-v1
        with:
          command: blast-radius
          only-changed: true
          comment: true
          github-token: ${{ github.token }}
```

Một số lưu ý về cách hoạt động, để không có gì khiến bạn bất ngờ trong một lần chạy trực tiếp:

- Comment được tạo **trước** khi job báo fail, do vậy một PR bị block vẫn sẽ mang theo lời giải thích về nguyên nhân. Mã thoát được bảo toàn — rủi ro critical vẫn làm bài kiểm tra fail.
- Danh sách file thay đổi đến từ API chứ không phải từ `git diff`: `actions/checkout` mặc định dùng `fetch-depth: 1`, do đó commit cơ sở không có trong lịch sử git ở local và diff sẽ sai hoặc rỗng.
- Đối với sự kiện `push`, cả hai flag đều bị bỏ qua (kèm theo một thông báo) thay vì làm lệnh fail — vì thế cùng một workflow có thể chạy trên event push mà không cần phải viết điều kiện ngoại lệ (special-casing).
- Việc cập nhật hoạt động bằng cách tìm đoạn mã đánh dấu `<!-- django-orm-lens: blast-radius -->`, thứ mà trình kết xuất markdown luôn tạo ra ở dòng đầu tiên.
- `github-token: ${{ github.token }}` là đủ; không cần PAT, không cần App.

## Số liệu thống kê Production (tùy chọn)

Tất cả những phân tích bên trên đều là tĩnh (static), điều này để lại một khoảng trống trung thực: mã nguồn không thể phân biệt được một bảng có bốn mươi triệu dòng với một bảng rỗng. Lệnh `migration-risk` tạm thời vượt qua điều này bằng một phương pháp ước lượng (heuristic) — *bất kỳ thứ gì được tạo ra sau file `0001_` đều được giả định là có dữ liệu* — đủ đúng để hữu ích, nhưng cũng đủ sai để gây phiền toái.

Cờ `--stats` sẽ thu hẹp khoảng trống này, và **django-orm-lens vẫn sẽ không bao giờ kết nối tới một cơ sở dữ liệu**. Bạn tự chạy một câu truy vấn chỉ đọc (read-only) và đưa lại kết quả cho công cụ:

```bash
django-orm-lens stats-sql > stats.sql
psql -At -d "$DATABASE_URL" -f stats.sql > stats.json     # truy xuất trên bản replica là ổn
django-orm-lens blast-radius --path . --stats stats.json
```

Khi đó báo cáo sẽ mang theo kích thước thực tế:

```
!! blog.post.author  [RemoveField]
     critical: remove_field_still_referenced (high)  blog/migrations/0002_drop_author.py:7
     blog_post: ~41 000 000 rows, 12.0 GB, 4 index(es) (ước tính)
```

Tại sao lại dùng một file mà không dùng connection string (chuỗi kết nối):

- Sẽ không có bất kỳ credential nào đi vào cấu hình CI, như vậy không có gì để rò rỉ.
- Câu truy vấn chỉ là một lần đọc từ `pg_stat_user_tables` cộng với `pg_total_relation_size`. Nó không thực hiện lệnh khóa (locks) nào và không đọc bất kỳ dữ liệu người dùng nào — chỉ tên các bảng và số đếm.
- File `stats.json` có thể được commit, review và diff giống hệt như bất kỳ đầu vào nào khác.

**Đây chỉ là các con số ước tính, và công cụ luôn nhấn mạnh điều đó.** Trường `n_live_tup` được duy trì bởi công cụ thu thập số liệu và được làm mới (refreshed) nhờ `VACUUM` / `ANALYZE`; quá trình autovacuum sẽ kích hoạt `ANALYZE` sau khi có khoảng 20% các hàng của bảng thay đổi, vì thế một bảng dữ liệu bận rộn sẽ bị sai lệch giữa các lần chạy. Ngay sau khi chạy `ANALYZE`, nó thường chính xác với biên độ sai số chỉ vài phần trăm. Như vậy là quá đủ cho một quyết định mà báo cáo này định hướng: phân biệt giữa bốn mươi triệu hàng và bốn trăm hàng.

Một bảng dữ liệu bị thiếu trong file `stats.json` sẽ được báo cáo là **unknown**, tuyệt đối không bao giờ báo cáo là rỗng (zero) — một model mà production chưa từng nhìn thấy không thể được hiểu là "an toàn để xóa bỏ". `Meta.db_table` được tuân thủ khi phân giải một model thành tên bảng của nó; nếu không, nguyên tắc `<app>_<model>` mặc định của Django sẽ được áp dụng.

## Ví dụ

```
!! blog.post.author  [RemoveField]
     critical: remove_field_still_referenced (high)  blog/migrations/0002_drop_author.py:7
       Removes field 'author' from 'post' but a field with the same name still exists in the current models.py.
       fix: Confirm no code path still reads/writes the field. Deploy the code change first, then run this migration.
     still referenced in 5 place(s): 2 certain, 1 likely, 2 possibly
       serializers/certain  blog/serializers.py:3  fields = ["title", "author"]
       views/certain  blog/views.py:5  return Post.objects.filter(author__id=request.user.id)
       templates/likely  blog/templates/blog/post.html:1  <p>{{ post.author }}</p>

summary: 1 target(s), 1 critical risk(s), 2 certain reference(s)
```

## Cấu trúc JSON

```jsonc
{
  "targets": [
    {
      "target": "blog.post.author",
      "app": "blog", "model": "post", "field": "author",
      "operations": ["RemoveField"],
      "worstSeverity": "critical",
      "risks": [ /* Các đối tượng MigrationRisk, như trong `migration-risk --format json` */ ],
      "impact": {
        "counts": { "certain": 2, "likely": 1, "possibly": 2 },
        "byLayer": { "views": [ /* các finding */ ] }
      },
      "cascade": null
    }
  ],
  "unscannedRisks": [ /* các rủi ro trên các phép toán phi phá hủy (non-destructive) */ ],
  "summary": { "targets": 1, "criticalRisks": 1, "certainReferences": 2 }
}
```

Các finding về ảnh hưởng sử dụng `line` và `column` **zero-based** (bắt đầu từ số không), khớp với extension VS Code và bộ LSP. Các trình kết xuất dưới dạng văn bản và markdown sẽ cộng thêm một trước khi in ra kết quả, bởi vì con người và các editor thường sử dụng dạng one-based (bắt đầu từ số một).

## Liên quan

- [`migration-risk`](migrations.md) — 16 rule đằng sau nửa phân tích rủi ro
- [`nplusone`](nplusone.md) — công cụ phân tích CI thứ hai
- `impact <name>` — quét tham chiếu riêng lẻ, dành cho khi bạn không muốn xem xét migration
