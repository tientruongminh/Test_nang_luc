# Câu 5 - Document Pipeline, Fingerprint, Versioning

## Assumption

Pipeline cần chứng minh idempotency và invalidation offline. Tôi dùng SQLite in-memory cho DB, object storage giả bằng content-addressed dictionary, và bytes text thay cho PDF parser thật. Điều quan trọng ở đây là identity contract, không phải OCR/PDF extraction.

## Flow

```text
ingest -> extract -> dedup -> chunk -> embed -> analyze
```

Upload đi qua các bước:

1. Tính `file_fingerprint = sha256(raw_pdf_bytes)`.
2. Ghi PDF vào `objects/<file_fingerprint>.pdf`, trích text và ghi text vào `texts/<text_fingerprint>.txt`, không phụ thuộc filename.
3. Tạo hoặc lấy `document` theo `document_key`.
4. Nếu cặp `(document_id, file_fingerprint)` đã có trong `document_version`, trả version cũ để tránh duplicate trong cùng tài liệu.
5. Nếu content mới, tạo `document_version` mới.
6. Tạo artifact cho extracted text, chunk, embedding và analysis.
7. Tạo downstream jobs và outbox event trong transaction DB.

## Fingerprint / Identity

| Layer | Identity |
| --- | --- |
| File | `sha256(raw_pdf_bytes)` |
| Document version | `sha256(document_key + file_fingerprint)` |
| Extracted text | `sha256(normalized_extracted_text)` |
| Chunk | `sha256(chunk_index + chunk_text)` |
| Embedding | `embedding:<model>:<model_version>:<chunk_fingerprint>` |
| Analysis | `analysis:<prompt_version>:<model>:<config_version>:<chunk_fingerprint>` |
| Task identity | `task:<job_type>:pipeline-v1:<document_fingerprint>` |
| Object key | `objects/<file_fingerprint>.pdf` |
| Extracted text key | `texts/<extracted_text_fingerprint>.txt` |

Vì object key dựa trên content hash, upload cùng PDF nhưng tên khác không tạo duplicate. Nếu PDF sửa một trang, `file_fingerprint` đổi, nên cùng `document_key` sẽ tạo `document_version` mới và downstream artifacts/jobs mới.

## Minimal Schema

Schema nằm trong `q5_document_pipeline/schema.sql` và có các bảng:

- `document`
- `document_version`
- `artifact`
- `job` (`task_identity` is unique and stable across retries)
- `outbox`

`document_version` giữ file/document fingerprint và stable object key. `artifact` giữ extracted text, chunk, embedding và analysis identities. `job` thể hiện downstream invalidation/recompute. `outbox` tránh mất event sau DB commit.

## Failure Modes

- Crash sau khi ghi extracted text vào object storage nhưng trước DB update: retry an toàn vì cả PDF và text key đều content-addressed và `put_if_absent`.
- Crash sau khi insert version nhưng trước khi commit jobs/artifacts: transaction rollback, không để lại orphan `document_version`/`job`; retry tạo version `1` bình thường.
- Upload duplicate cùng content khác filename: trả cùng `document_version_id`, không tạo version mới.
- Empty/poison document: tạo version `FAILED_NO_RETRY` với `failure_reason`, failed extract job có `attempt_count=1`; upload lại cùng bytes trả cùng version, không retry vô hạn.
- Retryable job failure: worker ghi `FAILED_RETRYABLE` và tăng `attempt_count`; retry thành công vẫn dùng cùng `task_identity`.
- Outbox dispatch failure: event giữ `PENDING`, lần retry chỉ đổi sang `SENT`, không tạo thêm document version.
- Cùng bytes nhưng `document_key` khác có version riêng cho từng tài liệu; object storage vẫn chỉ giữ một bản PDF và text.

Retry chỉ áp dụng cho lỗi tạm thời với backoff và giới hạn attempt; lỗi parser cố định đi vào DLQ/`FAILED_NO_RETRY` cùng `failure_reason`. Replay thủ công phải chỉ rõ `document_version_id` và parser version mới, được audit, rồi tái tạo riêng artifact/job chịu ảnh hưởng trong transaction. Worker nhận lại event outbox kiểm tra unique identity trước khi tạo task; không phát sinh thêm bản ghi khi replay cùng version.

## Test Commands

```bash
python -m unittest discover -s q5_document_pipeline/tests -v
```

Test bắt buộc đã có:

- `test_duplicate_same_content_different_filename_is_not_new_version`
- `test_modified_pdf_creates_new_document_version_and_downstream_jobs`
- `test_crash_after_object_write_can_retry_without_duplicate_object`
- `test_empty_or_poison_document_does_not_retry_forever`
- `test_job_task_identity_is_stable_across_retryable_failure`
- `test_failure_after_version_insert_rolls_back_without_orphan_rows`
- `test_outbox_dispatch_failure_leaves_event_pending_for_retry`

Expected output: duplicate cùng tài liệu không thêm version; PDF sửa một trang tạo version và jobs mới; crash sau khi ghi text có thể replay; poison document có một failed job; retryable task giữ nguyên identity; outbox failure retry được; hai tài liệu cùng bytes có version riêng.
