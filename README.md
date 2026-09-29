# Cairn

Cairn compiles selected evidence into a reviewable Markdown wiki and scoped project
context. Sources and human notes are preserved. Models propose changes; the owner
approves and applies them.

Implementation is in progress. See [the build plan](CAIRN_BUILD_PLAN.md) and
[acceptance tracking](docs/acceptance.md). Do not use this checkout with private data.

Python package: `cairn`; command: `cairn`. Development uses synthetic workspaces outside
the checkout. A private deployment requires a reviewed, pinned installation and a
verified execution boundary. No network or cloud processing is enabled by default.
