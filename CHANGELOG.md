# Changelog

Cairn uses semantic versioning. The version lives in `pyproject.toml` and
`src/cairn/__init__.py`, which must agree; managed installs adopt `stable` only when it
increases.

- **Major** releases need owner attention: a changed workspace or record format, a removed
  command, or a changed approval boundary.
- **Minor** releases add commands, workflows or guidance.
- **Patch** releases fix defects without changing behavior otherwise.

## 0.1.1 — 2026-10-10

- Documentation: rewrite the README for clarity and add the MIT license. No change in
  behavior.

## 0.1.0 — 2026-10-10

- First release on the `stable` channel: M0–M3 workflows, Finch reading, Quill writing,
  HTML views, journal library, and automatic updates of the managed runtime and the
  knowledge-base Quill.
