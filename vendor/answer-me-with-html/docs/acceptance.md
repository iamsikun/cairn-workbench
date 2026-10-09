# Portable edition acceptance

Status: portable revision 1 validated. Installation and rollback records are retained locally under `.install-backups/` when this release is installed.

Base: upstream 0.5.0, commit `19b2b5b07676d3e65c83ca9a7b6621f300b54c92`, imported locally as `d178109` without a Git remote. Source and generated bundle are maintained separately; bundle provenance is generated from the actual output.

## Scope and evidence

New regression coverage is in `test/policy.test.js`, `test/raw-html.test.js`, and `test/portable-browser.test.js`. It covers code traversal/symlink/sensitive aliases, resolved roots, image boundary independence, obfuscated executable URLs, offline assets and CSP, explicit raw/network exceptions, metadata that cannot grant permission, stable intro/panel code/image snapshots, deliberate refreshes, recoverable legacy snapshots, missing/duplicate selection, retries, atomic failures, and local-only automatic narration. Existing upstream behavior tests were retained and adapted where defaults intentionally changed.

A new preflight validates video visuals before calling a speech provider. Page controls honor reduced-motion preferences. The standalone CLI bundles parser-only CSS modules, avoiding a runtime dependency on external parser data files.

## Executed checks

- Final full upstream and portable suite: **784 checks, 782 passed, 0 failed, 2 skipped**. The same run passed copied-package smoke tests, license/provenance generation, and deterministic rebuild verification.
- Final snapshot recovery change: 89 relevant code/image/patch/config/policy and invariant tests passed, with no failures or skips. It follows the renderer's outer envelope, so lookalike panel classes in trusted custom markup cannot shift snapshots.
- Packaged CLI: Node 20.19.0, 22.14.0, and 24.0.0 on Linux ARM64, each from ordinary and space/non-ASCII installation paths. Render, file-based patch, repeated output-path retry, captions-only video, and disabled-by-default update checks passed without agent-specific environment variables.
- Chromium 154.0.8037.92: upstream layout and reply checks plus the portable browser check passed. Coverage includes 1440px/390px light/dark pages, keyboard focus, diagram expansion/Escape, reply collection, printed PDF, and reduced-motion controls. Desktop light and narrow dark screenshots were visually reviewed; narrow diagrams remain scrollable/expandable.
- Request observation: the default synthetic page requested only its own file, with zero page script exceptions. An explicitly trusted inline script attempting a fetch produced a connect-src CSP violation.
- Snapshot comparison: 432 upstream/current combinations, 432 intended differences limited to the new CSP and reduced-motion CSS, 0 unexpected differences, 0 pages changed by patching a panel with its own source.
- Bundle rebuilt twice with an identical SHA-256. Bundle SHA-256: `7d05f6c1fef90064520c25013cfacc2092fdccec0531612e3e23bab8fce7f1cb` (also in package PROVENANCE.json). The copied package includes upstream and dependency licenses.
- Skill creator's quick_validate.py: “Skill is valid!”; structural Agent Skills metadata/reference tests also passed.
- Synthetic installer exercise: replacement, checksum verification, backup, unrelated-file preservation, separate settings/pages preservation, and rollback passed.
- Mandatory isolation gate passed: non-root UID 65532, read-only root, no effective capabilities, no-new-privileges, loopback only, no Docker socket or supplied credential variables. Host-side inspection confirms network=none and one public staging mount.

Detailed logs and screenshots are retained locally in `validation-output/`. They are validation artifacts, not published material. The test image was acquired separately from Debian's public image/packages and verified official Node archives; the final processing image is independent of any application project. Its manifest is `sha256:706f268d95e9e752bd5cd4fdf34f8f93cbb9aec50417e61a975efda01c522751` (config/image ID `sha256:36c365f8d3d66dd379b510ea8a03f5204ee377a60d42db8b7e1841f525f97f21`). The recorded lockfile matches the acquired dependency image.

## Initial failures and their disposition

- Upstream tests assumed unconditionally trusted raw fences, external images, automatic cloud narration, and update checks. Fixtures/expectations now express the explicit permission model; new default-denial tests cover the restrictions.
- Importing the CSS parser's full index introduced an unbundled data-file dependency. Parser/walker submodules fixed it; copied-package smoke tests exercise the built bundle.
- Docker's implicit noexec scratch mount bypassed the mock ffmpeg executable. An explicit executable **synthetic** scratch mount restored that failure-path test inside the outer isolation boundary.
- Browser fixture setup needed explicit trusted-HTML flags, and export fixtures needed to inherit AM_CHROME. These are test setup corrections, not skipped tests.
- CSP failure events were not consistently reported as Network.loadingFailed by Chromium. The explicit-script restriction test now observes the browser's securitypolicyviolation event and checks connect-src, while the default-page test records every page request.
- The initial CSS URL walk treated a quoted selector value (`display: flex`) as a URL. Resource checks now inspect URL nodes and strings only in resource-bearing syntax; legitimate selector/content strings and image-set URLs have regression coverage.
- A browser profile cleanup raced Chromium child shutdown. Asynchronous retried cleanup resolved the fixture failure.
- Help text and containment error diagnostics changed; compatibility wording is retained without weakening the restrictions.

## Limits and skips

Live registration/discovery in agent products, macOS/Windows execution, real cloud narration, and subjective narration/semantic quality are not claimed. Linux ARM64 CLI checks do not establish those capabilities. Browser coverage applies to Chromium and the exercised synthetic fixtures. Mobile diagrams may intentionally scroll horizontally and can be expanded; this is distinct from page-level clipping.

The two recorded skips are the pid-1 ownership fixture (pid 1 belongs to the same container UID) and the upstream marketing-site distribution check (site/dist was not built; this is separate from generated answer pages). Neither is counted as a pass. That is a platform precondition, not an isolation exemption. `scripts/check-isolation.mjs` is a separate mandatory passing gate.

## Release contents and installation

The portable ZIP contains only the skill entry point, five focused references, generated CLI, upstream license, dependency licenses, and provenance. The maintained source repository retains local milestone commits and no remote. The archive is available under `dist/answer-me-with-html-portable.zip`; it can be supplied unchanged to another agent that meets the core requirements.

Installation copies only maintained package files into the requested existing skill location. It backs up the prior installation outside discovery directories, preserves unrelated files and separate settings/pages, verifies every installed checksum, and retains an install record plus a restore script. Rollback refuses to overwrite files changed after installation until the changes are reviewed. No other agent installation, remote, upstream issue/PR, or published site is created.
