# Technical assessment submission

The answer document and runnable offline examples are in [`submission/`](submission/).

- [Answer document](submission/final_answer.pdf): questions 1-10.
- [Code and test guide](submission/README.md): setup, per-question mapping, and commands.
- [Final test output](submission/test_outputs/final_test_run.txt): timestamped test run.

Requirements: Python 3.10 or newer. The tests use only the Python standard library and localhost fixtures.

Run from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s submission -p 'test_*.py' -v
```

Expected result: 27 tests pass. No credentials or live third-party services are needed.
