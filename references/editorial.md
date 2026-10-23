# Editorial guide

Write for a technically literate reader who has no internal project context.
Begin with the problem and vocabulary. Explain a concept once, then refer to the
chapter by title. Use a concrete example after an abstract definition. A claim
about present behavior needs evidence; a requirement or proposal needs an
explicit status. Never upgrade a source’s status while paraphrasing it.

Keep book narrative separate from exact protocol authority. Link the public
specification, section and version next to format or behavioral claims. Use
Pandoc footnotes for longer source notes. Explain a link’s relevance rather than
making the link carry the explanation. Distinguish observed examples from
universal promises. Do not invent command flags, wire fields, error codes,
performance measurements or guarantees.

Use English or Russian consistently per book. Preserve technical identifiers in
English and code in backticks. In Russian use «quotation marks», ё where needed,
and spaced em dashes. The filter binds short Russian words to their following
word and an em dash to its preceding word. Use real headings and Markdown
structure, without manually inserted print page breaks or raw HTML.

Keep diagrams narrow in purpose. Use one consistent visual vocabulary, readable
labels, a descriptive caption and a nearby explanation. Store the editable
source alongside a generated render and record both byte hashes. Avoid a single
crowded diagram that tries to replace a chapter. Figure numbering follows the
chapter automatically; choose `.tall` or `.landscape` explicitly when needed.

Before delivery, check that a rejection is described with its exact invariant
and limits, that examples do not imply unavailable functionality, and that the
book contains no internal conversation, private identifiers, task history or
private source links. An unresolved decision remains explicit in the project’s
normal decision log until its owner resolves it.
