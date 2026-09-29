# Acceptance evidence

Implementation is in progress. A checked item requires an executed test or inspected
artifact, not just code presence. Private activation and M4 are outside this goal.

| Stage | Status | Remaining |
| --- | --- | --- |
| M0 | Passed reference acceptance | 24 tests, lint, strict typing, 13 isolation checks |
| M1 | Pending | Ingestion, approval/apply, recovery, search, client packets |
| M2 | Pending | Bibliography, context, receipts, continuity demonstration |
| M3 | Pending | Domain workflows, restore, installed release, complete audit |

The brief's hard gates will be mapped to named tests as implementation proceeds.

M0 evidence collected by `bash scripts/check.sh` in the reference Linux container on
the macOS Docker host: **24 tests passed**, Ruff passed, strict mypy passed (16 files),
and **13 process-level isolation checks passed**.

- `test_foundations.py`: record round trips, deterministic sets, traversal, symlink and
  hard-link access, special files, case/Unicode collisions, root overlap, unsafe YAML,
  scope widening, confidentiality/processing inheritance, and cloud denial.
- `test_provider.py`: deterministic extractive fake; injected source remains data;
  job/result serialization; pinned, no-mount worker command; subprocess wire protocol.
- `test_schema_exports.py`: generated schema parity.
- `scripts/isolation_probe.py`: all 13 checks passed with a real unmounted synthetic
  host canary. Canonical/policy/approval writes, outbound TCP, DNS, and hostile child
  operations were denied. No Docker socket, host home, or forwarded credentials existed.

These checks cover a defined threat corpus. They do not prove semantic truth, universal
container security, or private-runtime readiness. M1–M3 remain required.
