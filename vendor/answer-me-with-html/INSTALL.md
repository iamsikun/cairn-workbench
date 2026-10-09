# Install the portable package

Use the complete `skills/answer-me-with-html` directory or its packaged archive. Choose a destination explicitly; do not discover or alter other agents' installations automatically. The core requirements are file access and Node.js 20+. No global configuration change, environment variable, runtime download, or package-manager installation is needed to run the bundle.

For an existing installation, back it up outside skill discovery directories, then copy the maintained package files into that destination. Preserve unrelated files and the separate data/settings directory. Verify `scripts/am.mjs` against `PROVENANCE.json`. Keep the backup and a manifest of files replaced/added so rollback can restore changed files and remove only newly installed package files.

Use the receiving host's normal mechanism to discover SKILL.md. Natural-language discovery remains enabled for explicit HTML requests. Do not add always-on rules. In hosts without a skills registry, the same instructions can be read directly. Deliver generated files through the host's supported mechanism.

Do not run generic upstream update commands on this maintained edition. Follow [staged maintenance](skills/answer-me-with-html/references/settings.md). The original upstream plugin adapters remain source history/context; this edition is distributed as the neutral skill directory.
