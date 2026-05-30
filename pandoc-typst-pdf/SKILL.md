---
name: pandoc-typst-pdf
description: >-
  Convert Markdown to PDF using Pandoc with the Typst engine — a fast, lightweight
  alternative to LaTeX (no TeX install needed, ~tens of MB). Produces clean output
  for technical docs, plans, summaries, and logs. Supports CJK fonts, code
  highlighting, tables, math, and custom Typst templates. Use when the user asks to
  "convert markdown to pdf with typst", "render md to pdf using pandoc", "md2pdf
  without LaTeX", or wants a typeset PDF without the LaTeX toolchain. Prefer over
  the `any2pdf` skill when the user explicitly mentions Pandoc, Typst, or wants the
  output to look typeset (rather than reportlab-rendered).
---

# Markdown → PDF via Pandoc + Typst

This skill describes the open-source pandoc + typst workflow. (The
youwu.today article it was modeled on advertises a paid Typst template; this
skill works without that template, and explains how to plug one in if the user
has it.)

## Prerequisites

```bash
pandoc --version   # need >= 3.1.7 for built-in --pdf-engine=typst
typst --version    # any recent version (0.10+)
```

If missing on NixOS, run via `nix-shell -p pandoc typst --run '...'`.
On other systems suggest the user install via their package manager
(`brew install pandoc typst`, `apt install pandoc && cargo install typst-cli`,
etc.) — do not install silently.

## Basic conversion

```bash
pandoc input.md -o output.pdf --pdf-engine=typst
```

That single command handles: headings, lists, tables, code blocks with
syntax highlighting (via Pandoc's built-in highlighter), images, footnotes,
blockquotes, and inline/display math (`$...$` and `$$...$$`).

## Common options

Pass Typst document variables with `-V`:

```bash
pandoc input.md -o output.pdf \
  --pdf-engine=typst \
  -V papersize=a4 \
  -V margin-top=2cm -V margin-bottom=2cm \
  -V margin-left=2.5cm -V margin-right=2.5cm \
  -V mainfont="DejaVu Serif" \
  -V monofont="JetBrains Mono" \
  -V fontsize=11pt \
  -V linkcolor=blue \
  --toc --toc-depth=3 \
  --number-sections
```

Equivalent settings can live in a YAML metadata block at the top of the `.md`:

```yaml
---
title: "My Document"
author: "Author Name"
date: "2026-05-11"
papersize: a4
mainfont: "DejaVu Serif"
monofont: "JetBrains Mono"
fontsize: 11pt
toc: true
toc-depth: 3
numbersections: true
---
```

## CJK text

Typst handles CJK natively — just pick a font that has the glyphs. Do **not**
use the LaTeX-style `CJKmainfont` variable; Typst's pandoc writer uses
`mainfont` for everything. For mixed CJK + Latin, choose a CJK font that
also covers Latin (e.g. Noto Sans CJK), or set `mainfont` to a CJK font:

```bash
pandoc cn.md -o cn.pdf --pdf-engine=typst \
  -V mainfont="Noto Serif CJK SC" \
  -V monofont="Noto Sans Mono CJK SC"
```

List installed fonts Typst can see:

```bash
typst fonts
```

## Code highlighting

Pandoc's default highlight style works. Pick a different one with
`--highlight-style=<name>`. Available: `pygments`, `tango`, `espresso`,
`zenburn`, `kate`, `monochrome`, `breezedark`, `haddock`, or a path to a
custom `.theme` file. Disable with `--no-highlight`.

```bash
pandoc input.md -o out.pdf --pdf-engine=typst --highlight-style=tango
```

## Custom Typst template

For full control over layout, pass `--template=path/to/template.typ`. Pandoc
fills the template with metadata and the rendered body. A minimal template:

```typst
#set document(title: "$title$", author: "$author$")
#set page(paper: "$papersize$", margin: 2cm)
#set text(font: "$mainfont$", size: $fontsize$)

#align(center)[
  #text(size: 1.6em, weight: "bold")[$title$] \
  #text(size: 1em)[$author$ · $date$]
]

$body$
```

Use `pandoc --print-default-template=typst > default.typ` to dump and
customize Pandoc's stock template.

If the user has the paid **youwu.today themekit** package, they install it
as a Typst local package at `$XDG_DATA_HOME/typst/packages/local/themekit/<version>/`
(or platform equivalent: `~/.local/share/typst/packages/local/...` on Linux,
`~/Library/Application Support/typst/packages/local/...` on macOS,
`%APPDATA%\typst\packages\local\...` on Windows) and pass
`--template=$XDG_DATA_HOME/typst/packages/local/themekit/<version>/pandoc/<theme>.typ`.

## Math, tables, images

- **Math**: works out of the box. Pandoc translates LaTeX math into Typst
  math. Display: `$$...$$`. Inline: `$...$`.
- **Tables**: grid tables and pipe tables both render. For column widths,
  use a YAML block or Pandoc's `{tbl-colwidths="[20, 80]"}` attribute.
- **Images**: `![alt](path.png){width=80%}` — relative paths are resolved
  against the input file's directory. SVG, PNG, and JPEG are supported.

## Gotchas

- **`mainfont` is mandatory**, even for Latin-only docs. Omitting it triggers
  `error: font fallback list must not be empty` from Typst's pandoc template.
  Set e.g. `-V mainfont="DejaVu Serif"`.

- **Nested template keys (`margin.x`, `margin.y`) need a YAML metadata file.**
  Pandoc's `-M margin.x=1.5cm` does *not* create nested structures — it sets a
  flat key called literally `margin.x`. To set margins use:

  ```yaml
  # meta.yaml
  margin:
    x: 1.5cm
    y: 1.5cm
  ```

  then pass `--metadata-file=meta.yaml`.

- **Pandoc wraps every table in `align(center)[#table(...)]`**, so columns
  declared `align: auto` inherit center alignment from the wrapper — text
  columns look centered. Override with a header file (`-H header.typ`):

  ```typst
  #show figure.where(kind: table): it => align(left, it.body)
  #show table: set align(left)
  ```

  Explicit `align: right` cells (numeric columns) keep their right alignment.

- **Variable fonts (e.g. Noto Sans CJK on NixOS) work despite a warning.**
  Typst prints `variable fonts are not currently supported and may render
  incorrectly`, but the PDF compiles and CJK glyphs render correctly. Do not
  abort on this warning.

- **Prefer this skill over `any2pdf` when CJK fonts are only available as
  variable OTF/TTC.** ReportLab (any2pdf's engine) cannot load fonts with
  PostScript (CFF) outlines and falls back to Helvetica, producing □/black
  rectangles for CJK. Typst handles them natively.

## Debugging

If conversion fails, run with `--verbose` and inspect the intermediate
Typst source:

```bash
pandoc input.md -o out.typ -t typst   # produce .typ instead of .pdf
typst compile out.typ                  # then compile manually to see errors
```

Common errors:

- *"font not found"* — check `typst fonts` for the exact name; Typst is
  picky about font family strings (case- and space-sensitive).
- *"unknown variable"* — a `-V` name doesn't match anything Pandoc's typst
  template references. Dump the template (see above) to see valid names.
- Pandoc < 3.1.7 — `--pdf-engine=typst` is unrecognized; upgrade Pandoc.
