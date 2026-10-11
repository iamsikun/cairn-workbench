# Integrity and execution boundaries

Documents and agent content are untrusted data. Models cannot choose save paths, impersonate
approval, adopt a decision or verify a claim merely by saving. The six tools fix collection
scope, use strict request schemas and accept no executable resources. Evidence bytes and
attributed observations are preserved separately from replaceable synthesis.

Filesystem operations reject traversal, symlinks, hard links and ambiguous names through
RootFS. Cooperating writers serialize; expected revisions detect stale clients and external
edits. Journals retain before/after bytes and conflict rather than overwriting unexpected
content during recovery. An independent editor need not honor the lock. A compromised owner
account or agent with independent filesystem access is outside this tool boundary.

The installed runtime uses bounded local extraction and optional rendering. These resource
bounds are not a claim that arbitrary native dependencies are an OS sandbox. Development
uses native tools with synthetic inputs and temporary settings. It does not establish
network or filesystem isolation. Process groups, deadlines and stream budgets bound
ordinary child execution; they do not confine hostile children that start new sessions.
Linux PDF extraction additionally limits address space; macOS retains CPU/input/output/time
budgets without that memory limit. No skipped mandatory check is a readiness pass.

Migration and managed-installation transition are explicit operations with verified recovery
material. Old validators are retained; no old executable is run against schema 4. Historical
worker and approval boundaries are in [legacy/threat-model-v3.md](legacy/threat-model-v3.md).
