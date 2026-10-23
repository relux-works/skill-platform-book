# Platform book

A Curator skill for writing platform books and chapters with a shared print
layout: mirrored A4 pages, PT Serif body, PT Sans headings, PT Mono code, a cover,
optional contents, status badges and chapter-numbered figures. English and
Russian scaffolds contain only original generic example text and artwork.

## Start a book

Provision the versions in `assets/toolchain.json`: Python **3.12.15**, Pandoc
**3.11**, WeasyPrint **70.0**, and pypdf **5.9.0**. Install Python packages from
`requirements-lock.txt` in an isolated environment; WeasyPrint also needs its
[platform native dependencies](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html).
On Linux the CI workflow documents the exact setup. Use one activated ordinary
venv for both pypdf and WeasyPrint. The entry point selects
`$VIRTUAL_ENV/bin/python3` explicitly, so Curator’s canonical system-command PATH
does not discard the provisioned environment. Missing or inconsistent activation
is refused. A separate WeasyPrint CLI is not used.

On macOS, provision native Pango libraries first. If they are outside the loader’s
default search path, set `PLATFORM_BOOK_LIBRARY_PATH` to their library directory
(for example `$(brew --prefix)/lib`). The launcher sets `DYLD_FALLBACK_LIBRARY_PATH`
only when executing Python; this survives macOS system-launcher filtering. Set
`DYLD_FALLBACK_LIBRARY_PATH` to the same directory when running Python tests
directly. Neither setting installs libraries.

```sh
python3.12 -m venv .temp/venv
. .temp/venv/bin/activate
python -m pip install -r requirements-lock.txt
scripts/platform-book ready
scripts/platform-book new docs/book --language en
scripts/platform-book figures docs/book
scripts/platform-book build docs/book .temp/book.pdf
scripts/platform-book check-pdf .temp/book.pdf --fonts "PT Serif" "PT Sans"
```

Pandoc is provisioned separately. Readiness checks Python packages and native
library loading and refuses a version mismatch or changed bundled font. Tools
are never silently installed or downloaded by the renderer.
The nine PT fonts are vendored at an exact public source revision and byte
hashes; their OFL licenses are included in `assets/fonts/`.

The scaffold’s `book.json` selects language and contents. Numbered Markdown files
live under `en/` or `ru/`; only the first carries title metadata. `src/figures.json`
records every editable source, render and SHA-256 pair. A hash detects changed
bytes; review is still needed to establish that a render represents its source.
Builds require local, declared Markdown figures and self-contained SVGs. Raw HTML
and symlinked figure/chapter inputs are rejected. Markdown attributes permit IDs,
classes and numeric `width`/`height` lengths only; `style`, `srcset`, attachment
attributes and other arbitrary HTML attributes are refused across AST node types.
WeasyPrint’s resource fetcher serves an in-memory allow-list of the bundled CSS,
pinned fonts and declared render bytes. HTTP, data URLs and undeclared local
files are refused before opening; nested CSS/SVG fetches use the same boundary.
Even a renderer-suppressed fetch denial prevents publication. Chapters may
contain ordinary web links as citations. The package declares its capabilities; schema 3 does
not enforce a runtime sandbox. Use trusted editorial inputs and tools.

Builds publish a PDF only after figure, renderer, page and font checks pass.
An existing output survives a failed build. Use `--expected-pages 2` for the
sample; real books have no fixed page limit. PDF checks verify all declared font
resources, including descendant fonts and Form XObjects, resolve to nonempty
font streams (null, empty, non-stream and unresolved references fail), and that
required families and extractable text are present. They do not prove visual quality.
Inspect representative pages before delivery.

## Install through Curator

`agent-skill.json` is the released schema 3 manifest. `scripts` and `assets` are
runtime roots; Curator freezes them together and exports `platform-book`.
Instructions and `references/` remain prompt-visible. Commands locate assets
relative to their frozen runtime, independently of the caller’s working directory.

Use **Curator v0.15.0-rc.4 or later with v2 content writers enabled**, through
**Skillfile schema 1**. The first tagged v2-writer cutover is rc.4. The real
installation test is validated with rc.8. Earlier package validation also
exercised main `1257799f5bf5f9bb929abd13ac70a17a68929662`; the venv-preserving
launcher needs no manager change. Schema 2 source freezing still carries a v1
context identity and rejects binary fonts with `audit.opaque.nul-byte`, at that tested main commit. Do not
use that lane for this package or bypass the opaque-input check.

For a committed source-checkout install test, run the command below. It clones
the exact committed package into a disposable manager source root, installs an
exact revision, checks the v2 marker and actual shim, and proves that later
source drift does not affect the frozen runtime. It never uses the operator’s
manager configuration. Commit changes before running it.

```sh
# Keep the ordinary venv above activated; no custom Python launcher is needed.
python3 tests/check_curator.py --curator curator
```

For a consuming project, declare a **full reviewed commit SHA** in schema 1
`Skillfile.json` (replace `REVIEWED_COMMIT_SHA` before use):

```json
{
  "schema_version": 1,
  "agents": ["codex_cli"],
  "skills": [{
    "name": "platform-book",
    "source": "platform-book",
    "git": "https://github.com/relux-works/skill-platform-book.git",
    "revision": "REVIEWED_COMMIT_SHA"
  }]
}
```

Register the project with `curator project add`, then run `curator install
PROJECT`. Curator acquires the repository below its configured source root and
installs that exact revision. Keep the pinned Skillfile in the consuming
project. Review and explicitly change the revision to upgrade. No root-input
policy or schema 2 lock is used on this lane. Do not edit an installed runtime.

The [released system-command contract](https://github.com/relux-works/curator-spec/blob/main/schemas/v1/common.schema.json)
expresses executable presence and a provisioning hint, **not tool version
constraints or a tool installer**. The package therefore uses only specified
manifest fields: Curator pins package bytes by exact Git revision; the checked build
command enforces tool versions from `toolchain.json`. No unsupported dependency
syntax or automatic provisioning is claimed. Unix execution is supported; no
Windows command path is declared.

## Tools and outputs

| Tool / entry point | Purpose | Output |
| --- | --- | --- |
| `scripts/platform-book ready` | Check selected Python, pinned packages, Pandoc, native loading and font hashes | Readiness verdict |
| `scripts/platform-book new DIR --language en` | Create an original book scaffold without overwriting DIR | DIR |
| `scripts/platform-book figures BOOK` | Parse Pandoc image AST, provenance, paths and SVG resources | Figure verdict |
| `scripts/platform-book build BOOK OUT.pdf` | Render with the bundled template, Lua and CSS; atomically publish | OUT.pdf |
| `scripts/platform-book check-pdf OUT.pdf --expected-pages N --fonts "PT Serif"` | Page count, font embedding, family and text checks | JSON verdict |
| `python3 -m unittest discover -s tests -v` | Positive and negative contract tests plus narrowing controls | Test report; scratch under `.temp/` |
| `python3 tests/check_curator.py --curator curator` | Real isolated Curator revision install/frozen-runtime check | Verdict; disposable `.temp/` fixture |
| `curator skill check .` | Validate the package manifest and context contract | Diagnostics |
| `pdffonts .temp/book.pdf` | Independent test-time font-embedding inspection (Poppler) | Font table |
| `pdftoppm -png .temp/book.pdf .temp/page` | Optional manual visual inspection (Poppler) | `.temp/page-N.png` |

The CI smoke build checks the original two-page sample, including all three font
families and figure provenance, then publishes the PDF as a workflow artifact.
Run tests in the activated venv with Poppler’s `pdffonts` available.
Python dependencies are fully version-pinned in `requirements-lock.txt`;
Pandoc’s Linux archive is verified against its release SHA-256 in CI.

## Relationship to the generic PDF skill

The generic PDF skill provides the same Pandoc + WeasyPrint approach and remains
appropriate for standalone reports. Its renderer accepts one document, its own
fixed template and a CSS override; it cannot select this cover template, combine
ordered chapters, apply the status/typography Lua filter, enforce figure
provenance or check book output before publication. This package therefore owns
one parameterized book renderer rather than wrapping or modifying that shared
renderer. The layout preserves the platform-book geometry, typography, cover,
contents, tables, badges and figure styles. Book names become metadata, Russian
and English captions follow language, and diagram sizing uses explicit classes.
