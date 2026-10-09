# Feedback and revisions

The optional HTML form downloads bounded JSON with bundle identity, target ID,
comment and optional suggested text. It keeps browser state in memory. Downloading
feedback sends nothing and changes no Cairn record.

The owner imports feedback as attributed evidence. Claimed authorship or approval
is not authority. Repeated identical imports are idempotent; comments without
suggested revisions await action.

For an owner-prepared revision packet, read its Quill editing guidance and supplied
response schema. Propose changes only to selected managed targets and retain their
base bindings. Preserve source bytes, human notes, catalog ownership, labels and
citation scope. Do not create targets, widen scope or manufacture adoption.

Return `job_id`, `input_hash` and `candidates`. The owner stages the response through
Cairn's existing proposal machinery. Stale inputs fail; staging is followed by
ordinary validation, explicit owner approval and recoverable apply. The agent does
not perform these owner operations merely because it received a packet.
