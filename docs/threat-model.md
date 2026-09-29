# Threat model

Untrusted inputs include documents, PDF structures, conversations, model output, and
external client results. They cannot change policy, create owner approvals, run shell
tools, widen a scope, or reach unrelated records through Cairn's worker protocol.

The trusted computing base includes the owner, reviewed installed software/dependencies,
the OS, the Docker engine, and the small host-side launcher. Workers run without owner
mounts, a host home, Docker socket, forwarded credentials, capabilities, or external
network. Their root filesystem is read-only and scratch, memory, CPU, and process counts
are bounded. The selected image must be pinned by its local digest.

A coding client with ordinary host shell access to owner files or the Docker daemon is
outside that boundary. An actor flag, prompt, virtual environment, or `.gitignore` cannot
make it safe. Do not hand such a client the private workspace. A compromised host or
container escape is outside the guarantee; the isolation suite tests a defined set of
hostile operations and cannot prove complete security.

Path access uses directory descriptors and refuses traversal, symlinks, hard links,
special files, and ambiguous case/Unicode names. YAML uses a safe loader, rejects duplicate
keys and aliases, and has size limits. SQL queries are parameterized; FTS syntax is built
from literal tokens. Model-provided filenames or shell patches are never executed.

Bare Markdown directories do not provide atomic visibility to arbitrary external editors.
Use the staged owner edit workflow for concurrent managed edits. Direct edits between
operations invalidate proposals. During crash recovery, unknown bytes are preserved and
require owner resolution rather than being silently overwritten.
