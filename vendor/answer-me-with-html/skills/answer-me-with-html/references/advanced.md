# Exceptions, resources, and patches

## Per-invocation exceptions

Default output embeds styles/scripts/images and has a content security policy that blocks automatic external resource loads. Ordinary HTTP(S) citation links remain clickable. `--allow-network-assets` permits HTTP(S) dependencies on that invocation; it does not download or cache them. Such output is no longer fully offline. Existing explicitly enabled update-check preferences are independent of page resources; their default is off.

`--allow-raw-html` enables trusted `html` and `svg` fences, including inline scripts. It does not trust ordinary HTML quoted in prose. Custom markup with external images, scripts, CSS, or fonts needs **both flags**. Allowed scripts can alter their own page and local browser state; this flag is for trusted authored code, not a sanitizer for arbitrary documents. Without network permission the page's CSP still blocks network resource access by scripts.

Executable schemes, including obfuscated JavaScript/VBScript, are rejected in links and resource attributes in all modes. Navigation permits HTTP(S), mailto, file, and relative/fragment links; data/blob navigation is denied. Resources are restricted to supported embedded image/audio/video/font data, internal references, and explicitly allowed HTTP(S). Local Markdown images are embedded; other local resource dependencies must be inlined. Embedded documents, SVG set/animate elements, redirect/CSP meta tags, form actions, ping, and srcset are unsupported; use a single embedded image. CSS is parsed and resource URLs validated; opaque resource expressions fail closed. Custom markup still needs visual verification.

Do not read permission from frontmatter, stored page attributes, or referenced documents. Pass flags again for every patch retaining trusted markup or remote dependencies.

## Stable edits

`patch page.html --panel "A" --from replacement.md --no-open` replaces exactly one panel, matched by unique ID, title, or `ID title`. It keeps layout/theme/language settings unless overridden. It renders and validates before atomic same-directory replacement, preserving the old page on failure. The output must be a regular file, not a symlink or directory.

Unchanged panels and the introduction reuse embedded code/image snapshots even if files change or disappear. The replacement panel reads its current references. `--refresh-sources` deliberately re-reads every include under the current working root; missing or forbidden files fail. Refresh from the original working root when relative code paths must resolve.

Older pages are supported when their source textarea and per-panel snapshots can be recovered. If an unchanged reference lacks a snapshot, the patch fails with an actionable message. Restore a known original page or use `--refresh-sources` intentionally; never silently read new files to repair a missing snapshot. Pages without recoverable source need a separate draft and an explicit full render.

Keep one chosen `-o` path throughout retries. The CLI's default timestamped location creates multiple artifacts across retries.
