# Câu 5 - Document Pipeline

## Flow

```text
ingest -> extract -> dedup -> chunk -> embed -> analyze
```

## Identities

- File fingerprint: SHA-256 of raw bytes.
- Document/version fingerprint: document key plus file fingerprint.
- Extracted text fingerprint: SHA-256 of deterministic extracted text.
- Chunk fingerprint: SHA-256 of text plus chunk index.
- Embedding identity: `embedding:<model>:<model_version>:<chunk_fingerprint>`.
- Analysis identity: `analysis:<prompt_version>:<model>:<config_version>:<chunk_fingerprint>`.
- Task identity: `task:<job_type>:pipeline-v1:<document_fingerprint>`.
- Stable object key: `objects/<file_fingerprint>.pdf`, independent of filename.
- Extracted text key: `texts/<extracted_text_fingerprint>.txt`.

## Run Schema/Test

```bash
python -m unittest discover -s q5_document_pipeline/tests -v
```

## Failure Handling

- Crash after extracted text object storage write but before DB update is safe because PDF and text keys are content-addressed.
- Uploading the same PDF with a different filename returns the existing document version.
- Empty or poison documents have a traceable `FAILED_NO_RETRY` version and a single failed extract job instead of infinite retry.
- Crash after DB version insert is rolled back without orphan `document_version` or `job` rows.
- Retryable job failure preserves the same `task_identity` and increments `attempt_count` on retry.
- Outbox dispatch failure leaves the event `PENDING` so it can be retried without recreating document versions.
