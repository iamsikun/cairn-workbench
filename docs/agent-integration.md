# Agent integration

Use [installation and connection instructions](installation.md) for Claude Code or Codex.
Cairn serves six operations over local stdio MCP with a fixed collection. The server's
initialize response and save-tool descriptions contain Cairn's persistent contract in
[src/cairn/saving/agent.md](../src/cairn/saving/agent.md).

The agent retrieves context, uses Finch for reading and Quill for substantial writing,
saves useful checkpoints, and reports returned IDs/revisions plus unfinished work. Semantic
connections are supplied by the connected agent; Cairn stores and validates their identities,
explanations, evidence and collection. Cairn never starts an autonomous model.

Settings tests use synthetic homes. Protocol trials use real subprocesses with scripted
requests. Neither proves actual Claude Code/Codex loading or Finch/Quill semantic quality;
those acceptance gates remain separately identified in [acceptance](acceptance.md).

Historical proposal-only integration remains documented in
[legacy/agent-integration-v3.md](legacy/agent-integration-v3.md).
