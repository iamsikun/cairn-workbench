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

## Paper reading and notes

Use Finch automatically for paper reading, explanation, critique, and co-reading,
including focused follow-ups. The installed runtime bundles Finch 0.2.0; an owner can
install the host skill with `cairn finch install --skills-dir /srv/agent-skills` if absent.
Follow its `references/cairn-workflow.md` on every invocation. With an owner-prepared
packet, complete the automatic response capture, concept proposal and validation
handoff before returning; no separate save request is needed. Report source/proposal IDs
or an explicit pending/blocked handoff. Approval/apply and personal read status remain
owner operations. Do not inspect private configuration or use contributor code against
a private workspace. Missing owner configuration does not authorize a guessed route.

## Writing

Use Quill for writing pages from Cairn material. Setup (`cairn init`/`restore`) installs it
for the knowledge base unless it is available machine-wide; otherwise use
`cairn quill install --skills-dir DIR`. Follow its `references/cairn-workflow.md`: write only from an owner-prepared
`cairn write begin` packet, return a `QuillResponse`, and let the launcher run
`cairn write finish`. Report the proposal ID or an explicit pending handoff. Never run
`cairn accept`, `approve` or `apply`; acceptance is the owner's step.
