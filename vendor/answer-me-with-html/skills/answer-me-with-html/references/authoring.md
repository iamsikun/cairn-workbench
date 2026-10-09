# Draft format and components

Use a saved UTF-8 Markdown file. The renderer handles layout, theme, SVG coordinates, and controls; start with built-in components.

````markdown
---
title: The reader's question
subtitle: The short answer
template: doc
lang: en
---
The evidence supports this conclusion. [Source](https://example.org/report)

## A Evidence
Explain the finding and its limits.

## B Implications
```callout info Proposed next step
Label recommendations as proposals.
```
````

`##` starts a panel. IDs such as `A` are optional; use stable unique titles or IDs when edits are likely. `sheet` makes a grid; `doc` makes a reading sequence. `theme: auto` selects a built-in theme; `blueprint`, `shadcn`, and `paper` are available. `mode` is `auto`, `light`, or `dark`. Sheet `cols` defaults to 3. A heading can end with `{span=2 meta="short note"}`; use span only for emphasis, because the layout sizes content automatically. One panel is valid.

| Information | Component | Syntax sketch |
|---|---|---|
| Relations or branches | `flow` or `flow LR` | `A -> B: label`; `A --> C` is dashed |
| Messages over time | `sequence` | `Client -> Service: request` |
| Hierarchy | `tree` | Indent child lines; `label \| description` |
| Entities and relations | `er` | Entity, indented fields; `User 1--* Order` |
| History | `timeline` | `date \| event \| evidence` |
| Measured values | `limits` | `label \| 13 / 20 \| unit` |
| Metadata | `kv` | `key: value` |
| Conclusion or caveat | `callout info` / `ok` / `warn` / `err` | Markdown body |
| Comparable evidence | Markdown table | Parallel dimensions; citations in cells or nearby |
| A consequential reader choice | `ask` | Question, `* suggestion \| reason`, `- alternative` |
| Existing code | code fence | `ts src=src/file.ts lines=18-30 hl=22`, empty body |
| Proposed code | code fence | `ts title="Proposed sketch"`, code body |
| Existing image | Markdown image | `![Caption](<path/to/plot.png>)` |

Run `node "<skill directory>/scripts/am.mjs" help <component>` for complete syntax, `help format` for frontmatter, or `list` for components. Replace placeholders with actual paths/names.

Flow/tree/er support `+ `, `- `, and `~ ` markers for structural changes. Unified diffs use a `diff file=src/file.ts` fence; preserve hunk counts. Mark illustrative code as such.

Code includes resolve from the working directory and must stay inside its canonical root, including symlinks. Sensitive-file names/directories and key-like content are excluded. Blocks above 40 lines warn and above 200 fail. Included source and images become part of the deliverable: use only material appropriate to that output.

Images resolve relative to the draft's directory (working directory for stdin/patch). Explicit absolute image paths are supported; this does not broaden the code-file boundary. PNG, JPEG, GIF, WebP, AVIF, and SVG up to 5 MB per file are supported. Alt text also becomes the caption. Remote images need the network exception. Do not invent an existing image or measurements; label illustrative data clearly.

Use asks only where the reader's answer changes the next step. The Reply control collects choices and panel comments for the reader to copy; it does not send them to an agent. Preserve unanswered decisions as unanswered.
