# Câu 3 - Agent Runtime Contract Simulator

## What Is Included

- `src/runtime.py`: deterministic offline simulator for the runtime contracts.
- Tests for pinned graph versions, cross-tenant resume denial, and fan-in behavior when required branches are `UNKNOWN` or missing.

## Contracts Covered

- A run pins the active graph at start time: moving the tenant's active graph from `support-agent@v7` to `support-agent@v8` does not rewrite an existing run.
- A tenant cannot resume another tenant's run, even if the graph name/version matches.
- Fan-in is blocked until every required branch in the pinned graph has `SUCCEEDED`; missing observations are treated as `UNKNOWN`.

## Run Tests

Run from the `submission/` directory:

```bash
python -m unittest discover -s q3_agent_runtime_tests/tests -v
```

