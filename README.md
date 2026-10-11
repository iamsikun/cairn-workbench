# Cairn

A personal knowledge base your agent develops with you: save readings, connect papers,
maintain learning notebooks, and produce visual explanations.

Markdown and editable visual resources preserve knowledge independently of any client.
Finch guides reading; Quill develops clear prose. Cairn stores revisions, relationships,
original evidence and your observations, with scoped retrieval, recovery and undo.

## Restructuring status

The direct-save implementation uses workspace schema 4. See CAIRN_BUILD_PLAN.md and
docs/acceptance.md for milestone evidence and remaining real-client trials. Historical 0.3.0 behavior
and tests are retained for compatibility; they do not prove the new workflow.

The workflow is init -> connect -> read/discuss -> save -> connect knowledge.
Ordinary saves require no grants, approval commands or Docker. Research is the default
collection; finance/life require separate selection. The collection is a tool boundary,
not a sandbox for the agent's independent filesystem access.

Requested HTML companions show visual overviews, architectures, comparisons and scenarios.
They track their Markdown and asset inputs. An interrupted render never loses a note.
Finch and Quill are independently installed and maintained; Cairn manages neither skill.

```sh
cairn init /synthetic/knowledge
cairn connect codex --workspace /synthetic/knowledge
```

These are illustrative paths. See [installation and agent integration](docs/installation.md),
[HTML companions](docs/notebook-html.md), [migration](docs/migration.md), and
[recovery and undo](docs/recovery.md). Ordinary commands never run a startup updater;
legacy maintenance commands require the explicit `cairn legacy` prefix.

## Development

Use the documented native Python/uv environment with synthetic data. Docker is not
needed for development, CI or releases. Never use a real home, private knowledge base,
credentials or client settings. See [development](docs/development.md).
Run bash scripts/check.sh for required checks and bash scripts/release_check.sh for
installed-package evidence. Missing mandatory checks are not passes.

This repository is the software checkout. Private knowledge bases stay outside it.
No real deployment, migration, client configuration, schedule changes or publication
occurs as part of development. Historical acceptance evidence remains in docs/acceptance.md.

## License

MIT. The vendored HTML renderer retains its own MIT license.
