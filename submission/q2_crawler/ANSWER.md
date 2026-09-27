# Câu 2 - Crawler Load More, Cursor, Retry, Session

## Assumption

Crawler cần chạy được offline, nên tôi dùng một localhost fixture thay cho website thật. Fixture cố tình tạo các lỗi mà crawler production thường gặp: DOM/button thay sau render, duplicate profile, `429 Retry-After`, `401` do session hết hạn, schema thiếu field và cursor loop.

## Architecture

```text
Local fixture page/API
  -> crawler request /profiles?cursor=...
  -> validate schema
  -> dedupe profile id
  -> write JSONL
  -> update seen_cursors
  -> stop on max_pages / empty cursor / cursor loop
```

Fixture phục vụ trang HTML `/`, API `/profiles?cursor=...` và `/refresh`. JavaScript thay node button bằng `replaceWith` sau mỗi render. Cursor rỗng đại diện cho page đầu. Page 1 trả `p1`, `p2` và `next_cursor=page2`. Page 2 lần đầu trả `429` với `Retry-After`, sau retry trả `p2` duplicate và `p3`. Page 3 trả profile thiếu `name` và `next_cursor=page2` để tạo loop đúng theo đề.

## Key Design Decisions

| Problem | Decision | Reason |
| --- | --- | --- |
| Button `Load more` bị thay DOM sau mỗi render | Fixture thay button node; crawler đọc API JSON được phép | Tránh stale element khi DOM bị replace |
| Duplicate giữa page 1 và page 2 | `seen_ids` theo profile id | Output JSONL chỉ có profile canonical một lần |
| `429 Retry-After` | Đọc header rồi retry cùng cursor | Tôn trọng rate limit và không bỏ page |
| `401` session expired | Gọi `/refresh`, cập nhật token, retry request cũ | Không mất logical page đang xử lý |
| Cursor loop | `seen_cursors` với cursor rỗng map thành `<empty>` | Dừng an toàn thay vì crawl vô hạn |
| Schema thiếu field | Validate `id` và `name`, log lỗi, skip record | Không ghi JSONL hỏng |

## Failure Modes

- Nếu API trả `429`, crawler retry cùng cursor và log `retry` với `retry_after`.
- Nếu API trả `401`, crawler refresh session rồi retry cùng cursor.
- Nếu cursor tiếp theo đã nằm trong `seen_cursors`, crawler dừng với `stop_reason=cursor_loop`.
- Nếu record thiếu field bắt buộc, crawler log `validation_error` và tiếp tục page hiện tại.
- Nếu `next_cursor` rỗng, dừng `end_of_results`; nếu response 200 thiếu `profiles` hoặc `next_cursor`, dừng `schema_error`.
- Tối đa một lần refresh sau 401 và ba lần retry sau 429 cho mỗi page. Hết ngân sách retry thì log `request_failed` và báo lỗi, tránh treo vô hạn.
- CLI in mỗi status log dạng JSON ra stderr; `cursor_loop`, `schema_error`, `session_refresh_failed` và `rate_limit_retry_exhausted` phát log `alert` để vận hành đối soát nguồn.

Nếu phải điều khiển browser bằng Playwright/Puppeteer, chờ response `/profiles` và trạng thái render (danh sách hoặc cursor cập nhật), sau đó tìm lại button bằng locator mỗi lần; không giữ ElementHandle cũ. API JSON chỉ được gọi trực tiếp khi endpoint được phép và có cùng phạm vi quyền với UI. Với nhiều worker, lưu token và phiên bản token ở shared store; một worker giữ lock/compare-and-swap để refresh, các worker khác đọc token mới rồi retry cùng cursor. `Retry-After` phải được đọc trước khi retry; production cần hỗ trợ cả số giây lẫn HTTP-date và áp dụng rate limiter chung cho các worker.

## Test Commands

```bash
python -m unittest discover -s q2_crawler/tests -v
```

Test bắt buộc đã có:

- `test_duplicate_profile_is_deduped`
- `test_429_and_401_are_retried_with_refresh`
- `test_cursor_loop_stops_safely_and_logs_invalid_schema`

Expected output: `p1,p2,p3` một lần trong JSONL; có log `401_session_expired`, `429_rate_limited`, `duplicate_profile`, `validation_error`; dừng `cursor_loop` ở page 3. Các test bổ sung kiểm tra trang HTML, cursor rỗng, schema thiếu và retry budget.

## Offline Files

- Fixture: `q2_crawler/fixture/server.py`
- Crawler: `q2_crawler/src/crawler.py`
- Tests: `q2_crawler/tests/test_crawler.py`
- JSONL output path khi chạy manual: `q2_crawler/output/profiles.jsonl`
