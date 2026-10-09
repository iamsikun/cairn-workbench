# Data-only application profile

`src/application.js` exports `renderApplication(document, options)`. It renders a
versioned JSON document into fixed offline templates. It parses no Markdown, reads
no code/image paths, configuration or updates, and opens no browser. Existing
`am` authoring, patch and video behavior is unchanged.

The caller supplies sections, evidence anchors and optional raster assets by ID,
MIME type, base64 bytes and SHA256. Imported strings are escaped. Navigation accepts
HTTP(S) links without credentials; resources are embedded verified rasters only.
Executable URLs, unavailable references and malformed assets fail. The default CSP
permits only the bundled interaction script hash and denies network connections.

`interactions: false` removes scripts and interactive controls. `embedSource: true`
can include caller-supplied text for applications that explicitly need it; the
Cairn profile never enables source embedding. Neither option is read from imported
document fields. The executable `bin/application.js` uses the fixed default profile.

Build with `node scripts/build-application.mjs OUTPUT.mjs`. Run unit tests and the
mandatory Chromium test `test/application*.test.js` in the documented isolated
container. Keep this source, tests and build script synchronized with the workbench
vendor snapshot. Rebuild generated files; never patch the bundle by hand.
