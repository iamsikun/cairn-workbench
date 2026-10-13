# Link policy

Notes must stay useful on any machine and after temporary folders are cleared, so every reference
to a paper or source points to something durable.

**Zotero first.** A paper that is in the user's Zotero library is referenced by its Zotero item,
not by a web URL; `fix-links` rewrites such URLs daily and `zotero-sync` adds missing papers to
Zotero. The note's front matter keeps `source` and `url` as the paper's identity.

**Allowed**
- For a paper not yet in Zotero: its canonical URL (`https://doi.org/<doi>`,
  `https://arxiv.org/abs/<id>`, or the publisher or proceedings page).
- The Zotero item: `zotero://select/library/items/<KEY>`; its PDF:
  `zotero://open-pdf/library/items/<ATTACHMENT_KEY>`; a collection:
  `zotero://select/library/collections/<KEY>`.
- Other notes: `[[slug]]`.
- The journal catalog's pages in its data folder (`cairn-catalog paths`), or `cairn-catalog serve`.

**Not allowed**
- `/private/tmp/...`, `/tmp/...`, `file://...`
- `research/resources/...` or any other raw working files (cite the Zotero item or URL they came from;
  raw evidence is kept outside the knowledge base)
- `~/.codex/attachments/...` or any other agent's private upload folder

**Preferred form for a paper's source line**

```
- Paper: [Zotero](zotero://select/library/items/EE3TRR9S) · [PDF in Zotero](zotero://open-pdf/library/items/D333Q84T)
```

In running text, link the paper's name to its Zotero item: `[Reflexion](zotero://select/library/items/TWRH7FVX)`.
When a table row already has a Zotero column, leave the title unlinked.

When neither a URL nor a Zotero item exists (for example a pasted summary), describe the source in
plain text ("pasted ChatGPT summary supplied by the user on 13 October 2026") without a link.

Exact versions, page fragments, labels and user annotations are preserved. Ambiguous local
references stay unresolved for review; they are never silently reassigned to the current paper.
Quoted source evidence and code samples are left unchanged.
