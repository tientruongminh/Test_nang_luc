# Câu 2 - Offline Crawler Fixture

## What Is Included

- Localhost HTML page at `/` with a replaced `Load more` button; API `/profiles`, `/refresh`, `401`, `429 Retry-After`, duplicate profiles, missing-field payload, and cursor loop.
- Crawler with max 3 pages, profile dedupe, `seen_cursors`, session refresh, retry handling, JSONL output, and structured logs.
- Tests for duplicate handling, `429` + `401`, and cursor-loop stop.

## Run Fixture Manually

```bash
python -m q2_crawler.fixture.server
```

The server prints its localhost URL.
Open that URL in a browser to exercise the three-page Load more flow.

## Run Crawler Manually

```bash
python -m q2_crawler.src.crawler http://127.0.0.1:8000 q2_crawler/output/profiles.jsonl
```

For normal use, run the tests; they start the fixture on an available port automatically.
The crawler prints status logs as JSON lines to stderr and a final count/stop reason to stdout.

## Run Tests

```bash
python -m unittest discover -s q2_crawler/tests -v
```

## Expected Output

- JSONL contains deduplicated valid profiles only.
- Logs include page, cursor, retry, refresh, validation error, and final stop reason.
- The fixture returns page 3 with `next_cursor=page2` to prove cursor-loop protection.
