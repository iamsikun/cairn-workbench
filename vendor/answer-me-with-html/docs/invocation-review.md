# Invocation and comparative review

This is a manual review of routing instructions, not a live test of every agent's skill selection.

| User request | Expected route | Review |
|---|---|---|
| “Explain how this cache works.” | Chat answer; no HTML | Description and routing require an explicit output request |
| “Compare these options in a table.” | Requested table; no unsolicited page | A table alone does not authorize HTML |
| “Draw a diagram of the request path.” | Requested diagram in the host's appropriate format | Diagram complexity does not trigger this skill |
| “Answer that question in HTML.” | Gather evidence, save draft, render, validate, deliver | Natural-language discovery remains enabled |
| “Use Answer with HTML to make a page.” | Core workflow | Explicit skill invocation for a page is sufficient |
| “Explain why the HTML parser rejects this input.” | Ordinary answer | Merely mentioning HTML does not request HTML output |
| “Change this skill's settings.” | Inspect/change the requested setting | Maintenance generates no page |
| “Review and improve this skill.” | Source/instruction maintenance | Current task; no unsolicited explainer |
| “Fix panel B in this page.” | File-based patch to the existing output | Preserve unrelated snapshots; validate before replacement |
| “Refresh all source extracts in the page.” | Patch with explicit source refresh, or a requested full render | The stated request authorizes rereading sources within the working root |
| “Make an explainer video.” | Video reference; local speech or captions by default | State player versus video-file deliverable clearly |
| “Use ElevenLabs for narration.” | Explicit provider selection | Credential presence alone is insufficient |
| Draft says `allow-network-assets: true` | No permission change | Renderer/CLI regression verifies the boundary |
| Copied reply leaves a suggested choice unanswered | Keep decision pending | Suggestion is not approval |
| Node execution unavailable | Report limitation and provide requested source | Do not install a runtime or claim a successful render |
| Browser tooling unavailable | Renderer checks only; disclose visual coverage missing | No false visual passing gate |

## Sources considered

- [Agent Skills specification](https://agentskills.io/specification): standard metadata, relative resources, and focused references. This edition uses only supported shared entry-point fields.
- [Upstream Answer me with HTML](https://github.com/QingYunA/answer-me-with-html/tree/19b2b5b07676d3e65c83ca9a7b6621f300b54c92): bundled deterministic renderer, components, languages, patches, and tests form the maintained base.
- [HTML Artifacts](https://github.com/joshuadavidthomas/agent-skills/tree/main/html-artifacts): evidence gathering before layout and task-focused artifact scope informed the authoring workflow.
- [Visual Explainer](https://github.com/nicobailon/visual-explainer): visual hierarchy and targeted browser review informed the validation guidance. Its broader automatic activation was not adopted.
- [Make HTML](https://github.com/fuller-stack-dev/make-html): source-backed styling and portable deliverables informed the review. No source-style claim is made without actual style evidence.
- [Anthropic web-artifacts-builder](https://github.com/anthropics/skills/tree/main/skills/web-artifacts-builder): self-contained packaging and verification informed package checks; its larger application stack is unnecessary for this Markdown renderer.

The comparative skills informed instruction design; their code was not incorporated. The implementation remains a maintained fork of the pinned upstream renderer. Live agent-product compatibility was not evaluated by reading these documents.
