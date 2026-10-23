---
name: platform-book
description: "Write or revise a platform book, book chapter, technical book or PDF book with the shared print layout. Use for книга, глава, PDF-книга, книга о платформе and book chapter requests; includes outline, editorial review, figure provenance, scaffold and checked PDF build."
---

# Platform book

Turn an idea or design into a readable explanation with the bundled book layout.
Use the repository’s task tracker before editing. Work in the book’s language;
keep technical identifiers and quoted source terms exact. Ask for missing product
or architecture decisions; do not silently turn a proposal into a decision.

The installed `platform-book` command locates its frozen runtime assets itself.
Resolve `<project>/.agents/bin/platform-book` first, then the manager’s
`global/bin/platform-book`, then a bare command validated with `command -v`
(POSIX) or `Get-Command` (PowerShell). Do not depend on shell-profile activation.
This package exports a Unix command only; Windows execution is not declared.
In a source checkout only, the entry point is described in README. Read
[the editorial guide](references/editorial.md) before drafting.

## 1. Establish the book and outline

For a new book run:

```sh
# Activate the provisioned ordinary Python venv first (README setup).
platform-book ready
platform-book new docs/book --language en
```

Use `--language ru` for Russian. The command refuses an existing destination.
The original sample contains a cover and one short chapter. Keep the two-page
limit for the example only; real books may have any checked page count.

Choose the audience, question, scope, language and source of authority. Record
an outline in the project’s normal task/documentation flow. Each chapter should
answer a concrete question. Establish concepts before relying on them.

## 2. Write and review

Put chapters in `en/NN-slug.md` or `ru/NN-slug.md`, starting at `00-`. Filename
order is reading order. Put Pandoc YAML title metadata only in the first file:
`title`, `subtitle`, `brand`, optional `author`, `date`, and `notes`.
Set `language` (`en` or `ru`) and boolean `toc` in `book.json`.
Use one `#` heading per chapter, then `##` and `###`. The introduction starts
at chapter 0. Refer to chapters by title; numbering may change.

Explain what the concept is, why it matters, how it works, then give a concrete
example and its status. Prefer short connected paragraphs. Use tables for
comparisons and steps for actual sequences. State limits beside guarantees.

Use only these status markers (literal examples belong in backticks):

| English | Russian | Meaning |
| --- | --- | --- |
| `⟦working today⟧` | `⟦работает сегодня⟧` | Implemented, with current evidence |
| `⟦decided⟧` | `⟦решено⟧` | An explicit decision |
| `⟦proposed⟧` | `⟦предложено⟧` | A proposal |
| `⟦specification⟧` | `⟦спецификация⟧` | Defined by an identified specification |
| `⟦open⟧` | `⟦открыто⟧` | An unresolved question |

Unknown complete markers fail the build, including adjacent markers. A partial
marker is ordinary text, so editorial review must catch unmatched delimiters.
Do not present internal tasks, review conversations, host paths, identities or
private links as public book content. Cite public, versioned authority near the
claim; use Markdown links or footnotes, never invented formats or guarantees.

## 3. Prepare figures

Keep editable sources in `src/`, renders in `diagrams/`, with matching stems.
Use a focused diagram, caption and nearby explanation. Follow a relevant diagram
skill when available. The scaffold has an original self-contained SVG example.

```markdown
![A caption](../diagrams/reading-flow.svg)
![A tall diagram](../diagrams/long-flow.png){.tall}
![A wide diagram](../diagrams/wide-flow.svg){.landscape}
```

Declare every source/render pair in `src/figures.json`, keyed by its lowercase
hyphenated stem. Each record has exactly `source`, `render`, `source_sha256` and
`render_sha256`. Paths are relative to the book; hashes are SHA-256 of the actual
bytes. Update a render and both recorded hashes after reviewing its source.
Hashes detect drift; they do not prove the render corresponds to the source.
Use Python’s `hashlib.sha256(path.read_bytes()).hexdigest()` to compute them.

Images must be local Markdown figures (`png`, `svg`, `jpg`, `jpeg`). Reference
syntax, IDs/classes and numeric width/height attributes work. Arbitrary HTML
attributes, including style and srcset, are refused. Raw HTML, symlinks,
unlisted files, stale hashes and external SVG resources fail validation. SVGs must be self-contained.
The checker does not render diagram source languages; generate renders first.

## 4. Build

```sh
platform-book figures docs/book
platform-book build docs/book .temp/book.pdf
platform-book check-pdf .temp/book.pdf --fonts "PT Serif" "PT Sans" "PT Mono"
```

The build validates figures, serves only declared assets through WeasyPrint’s
fetch allow-list, renders with Pandoc and WeasyPrint, then checks page
count and font embedding before atomically publishing the PDF. A failed build
preserves an existing output. Add `--expected-pages N` only for a fixed layout
contract. PT Mono is expected only when the book contains code. `ready` checks
exact pinned tool versions, the PDF parser and all nine bundled font hashes.
Provision tools as described in README; this skill does not install them.

## 5. Inspect and deliver

Inspect the cover and representative body, table, code, badge, tall and landscape
pages visually. Check clipping, missing glyphs, captions, reading order, running
headers, links and page breaks. Embedded fonts and a page count do not prove
visual quality. Verify public-content hygiene and claims against their cited
versions. Attach the PDF and validation evidence through the project’s normal
delivery flow; keep scratch renders under `.temp/`.
