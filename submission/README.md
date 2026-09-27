# Technical assessment: code package

# Environment and tests

Python 3.10+ and the standard library are sufficient. Run from this directory:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s . -p 'test_*.py' -v
```

Expected result: 23 tests pass. The timestamped run is in `test_outputs/final_test_run.txt`.

## Run Per Question

```bash
python -m unittest discover -s q2_crawler/tests -v
python -m unittest discover -s q3_agent_runtime_tests/tests -v
python -m unittest discover -s q5_document_pipeline/tests -v
```

## Mapping

| Question | Folder | Purpose |
| --- | --- | --- |
| Câu 2 | `q2_crawler` | Offline crawler with localhost fixture, retry, refresh, dedupe, cursor-loop handling |
| Câu 3 | `q3_agent_runtime_tests` | Agent runtime simulator for pinned graph, cross-tenant, and UNKNOWN/fan-in contracts |
| Câu 5 | `q5_document_pipeline` | Document ingestion schema, task identity, versioning, outbox, and failure-injection tests |

## Scope and assumptions

- The code demonstrates the contracts described in `final_answer.pdf`; it is an offline simulation, not production infrastructure.
- Q2 and Q5 are implemented as executable offline simulations because the prompt requires fixtures, tests, and failure-mode evidence.
- Q3 is included as executable evidence for the runtime contracts that are easiest to regress: graph pinning, tenant isolation, and fan-in over missing/unknown branches.
- Other questions are answered in `final_answer.pdf`; this trimmed code package keeps only the code/minh chứng folders that require runnable artifacts.

## Limitations

- The Python crawler uses the fixture's permitted JSON API. The fixture's HTML Load more flow was also checked in a browser, but browser automation is not a runtime dependency.
- No LLM provider, Kafka, production object storage, GPU, or PostgreSQL server is used.
- The crawler fixture intentionally runs on localhost only.
- The document pipeline stores object bytes in a local in-memory fixture for tests.
- Câu 7's chronological train/validation/test split is a document/PDF answer requirement, not a code folder in this trimmed package.

## Deliverables

- Answer PDF: `final_answer.pdf` (questions 1-10).
- Runnable code, SQL, fixtures, and tests: Q2, Q3, and Q5 folders listed above.
- Test evidence: `test_outputs/final_test_run.txt`.
- Optional ZIP package: `../submission.zip` (the repository itself contains the same submission files).
