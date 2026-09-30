The next useful step is to **specify the tiny bilingual baseline**, which I’ve done below. Execution remains pending.

The permitted [context.json](context.json) records an unresolved two-character Chinese query test, proposes Chinese/English/absent-evidence cases, and reports that title-only retrieval lost provenance. Its owner-adopted decision requires stable source IDs, source versions or hashes, and exact evidence locators. These support testing retrieval and provenance together.

**Proposed synthetic test**

Use these exact UTF-8 source bodies without trailing newlines. Each source has version `1`; compute its SHA-256 from the source bytes when preparing execution.

| Source IDScopeSource body |           |                                    |
| ------------------------- | --------- | ---------------------------------- |
| `synthetic_a`             | `study_a` | `海风推动风车。`                          |
| `synthetic_b`             | `study_a` | `wind drives the turbine.`         |
| `synthetic_c`             | `study_b` | `海风推动风车。 wind drives the turbine.` |

Baseline: filter by scope first, then perform case-sensitive literal substring matching without normalization. Return every matching source with its ID, version, SHA-256, exact matching quote, and zero-based, half-open Unicode code-point offsets.

| QueryScopeExpected evidence |           |                        |
| --------------------------- | --------- | ---------------------- |
| `海风`                        | `study_a` | `synthetic_a`, `[0,2)` |
| `wind`                      | `study_a` | `synthetic_b`, `[0,4)` |
| `月球`                        | `study_a` | Empty result           |
| `海风`                        | `study_b` | `synthetic_c`, `[0,2)` |

Pass criteria: exact expected matches and locators, complete provenance, no cross-scope results, and no invented evidence for the absent query. This tests literal retrieval mechanics; it does not establish semantic or cross-language retrieval quality.

**Structured session receipt**
```json
{
  "receipt_type": "study_session",
  "context_id": "context_2ec4ccddc76d4df85953e1d88ef216e0",
  "status": "test_design_completed",
  "completed": [
    "Read the permitted context file",
    "Specified synthetic fixtures, baseline behavior, and expected results"
  ],
  "evidence_basis": {
    "context_sections": [
      "current_decisions",
      "failed_approaches",
      "open_issues",
      "next_action"
    ],
    "qualification": "Prior findings are context reports, not independently reproduced."
  },
  "files_accessed": ["examples/continuity/context.json"],
  "files_modified": [],
  "network_used": false,
  "experiments_run": [],
  "observed_experiment_results": null,
  "proposed_decisions": [],
  "limitations": [
    "Fixture hashes have not been computed",
    "Retrieval behavior remains untested",
    "Repository binding is recorded as unbound"
  ],
  "next_action": "Run the specified cases in the documented development container once access to its instructions and execution assets is permitted."
}
```
