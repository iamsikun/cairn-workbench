# Language and writing checks

Write in the user's language. Frontmatter `lang` accepts tags such as `en`, `zh`, `zh-Hant`, `ja`, `fr`, or `ar`. Set it explicitly for non-English Latin-script text, ambiguous short passages, mixed-language pages, or an exact regional/script tag. Detection is heuristic; unsupported interface languages fall back to English labels while retaining the declared document language.

The STE-inspired writing check is advisory by default (`style: 80`). `style: strict` prevents output when checks fail; `style: off` disables them. It is not certification against an external standard and does not check factual accuracy.

Prefer active verbs, consistent terminology, and one idea per sentence. English checks include vocabulary and length (20 words for steps, 25 for descriptions). Chinese checks include wording and length (35 characters for steps, 45 for descriptions). Other languages receive general length checks; Japanese uses character limits. Paragraphs longer than six sentences warn. Inspect diagnostics in context: quotations, citations, domain terms, and uncertainty may justify retaining warnings. Do not rewrite evidence to satisfy a heuristic.
