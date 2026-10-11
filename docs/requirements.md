# Direct-save requirements and evidence

The current requirements are the [build brief](../KNOWLEDGE_WORKBENCH_BUILD_BRIEF.md) and
[R1–R6 build plan](../CAIRN_BUILD_PLAN.md). The [acceptance log](acceptance.md) records each
executed gate separately from actual agent-client and semantic-quality trials.

| Requirement | Implementation | Meaningful checks |
| --- | --- | --- |
| Preserve readings independently of enrichment/rendering | saving/service.py, transactions/writer.py | Retry/no-op, concurrent clients, stale bundled topic, crash recovery, external conflicts |
| Version knowledge and original observations | saving/models.py, service.py | Identity/versioning, retained observations, selective undo, located quotes |
| Connect papers and learning notebooks | saving/references.py, retrieval.py | Explained links/backlinks, aliases, questions, rejected-link memory |
| Scope before content/metadata/ranking | Book collection, retrieval, MCP, views | Cross-collection targets denied, isolated search/HTML, strict tool inputs |
| Simple agent integration | saving/cli.py, mcp.py, connections.py, agent.md | CLI/stdio subprocess, both settings formats, repair and unrelated settings |
| Optional local extraction | saving/sources.py | URL-only, unknown metadata, failed/valid PDF, retained original bytes |
| Derived HTML | saving/views.py | Freshness, snapshots, render failure, feedback retries, deterministic scenarios, browser checks |
| Recoverable migration and installation transition | saving/migration.py, backup.py, installation.py | Schemas 1–3, hash inventories, interrupted conversion, proposal retention, scheduler/updater races |

Historical requirements and evidence remain in [legacy/requirements-v3.md](legacy/requirements-v3.md).
They do not establish direct-save correctness. No private deployment or publication is included.
