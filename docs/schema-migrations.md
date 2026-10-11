# Workspace schemas

New knowledge bases use workspace schema 4 and knowledge record schema 2. Existing formats
are never rewritten during reads. Use the explicit, backed-up [migration procedure](migration.md)
for schemas 1–3. Backup payloads keep version-specific validators. Public JSON schemas are
exported from the typed models and checked for parity.

Historical schema 1–3 operations remain in
[legacy/schema-migrations-v3.md](legacy/schema-migrations-v3.md).
