# Answer with HTML — portable maintained edition

An explicit request for an HTML answer becomes a self-contained page from a saved Markdown draft. Ordinary questions remain ordinary answers. Any agent that can read files, write drafts, and execute Node.js 20+ can use the core skill; product-specific registration and previews are optional.

This local edition starts from upstream 0.5.0 at `19b2b5b07676d3e65c83ca9a7b6621f300b54c92`. See [provenance](skills/answer-me-with-html/PROVENANCE.json), [acceptance evidence](docs/acceptance.md), and the [upstream project](https://github.com/QingYunA/answer-me-with-html). No live compatibility claim is made for untested agents or operating systems.

The portable package is the entire `skills/answer-me-with-html` directory. It needs no npm install at use time. Read its [SKILL.md](skills/answer-me-with-html/SKILL.md) and [installation instructions](INSTALL.md).

```text
node "/path/to/skill/scripts/am.mjs" render "/path/to/draft.md" -o "/path/to/answer.html" --no-open
```

Pages are offline by default. Trusted HTML/SVG fences need `--allow-raw-html`; HTTP(S) assets need `--allow-network-assets`. Each invocation must opt in. Citations remain clickable. Patches preserve snapshots in unchanged panels and atomically replace a validated page. `--refresh-sources` deliberately refreshes includes. Automatic narration uses local speech or captions, never a cloud credential alone.

Authoring, language, video, and maintenance references live beside the skill. Updates are staged source changes followed by build, tests, checksum verification, and a backed-up replacement; generic self-updates would lose these modifications. Do not edit generated `am.mjs` by hand.

## Development

Read [development and isolation](docs/development-portable.md). Acquire public dependencies separately; execute contributor code in an isolated container with synthetic data and no external network, credentials, private mounts, or Docker socket. Run the upstream suite plus portable regressions, Node 20/22/24 package smoke tests, browser checks, snapshot review, and rebuild consistency checks. Record failures and skips honestly.

The original source, license, examples, site, and tests are retained. The upstream history imported into this standalone local repository has no configured remote. Legacy marketing/reference documents are historical; the maintained skill references govern this edition.
