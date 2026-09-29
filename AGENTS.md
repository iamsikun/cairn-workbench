# Working on Cairn

Read `KNOWLEDGE_WORKBENCH_BUILD_BRIEF.md` and `CAIRN_BUILD_PLAN.md` before changing boundaries.
Develop and test with synthetic data only. Do not inspect, mount, or ingest a real private
workspace, a home directory, or private credentials. Public fixtures and documentation
must use synthetic names and paths. Never add a remote or publish automatically.

Run contributor code through the documented development container. The worker image
must have no network, owner filesystem, credentials, or Docker socket at processing time.
Do not turn a skipped isolation check into a passing readiness gate.

Keep source bytes and human notes immutable to model proposals. Approval and canonical
apply remain owner operations. A model-supplied actor or approval field is not authority.
Preserve the six record types, explicit state machine, source locators, scoped retrieval,
and recoverable writer. Keep schema exports synchronized with the typed models.

Use small milestone commits and maintain `docs/acceptance.md` with honest evidence.
Run meaningful tests for changed boundaries and failure modes; do not claim that fake
provider results prove semantic quality or production readiness.
