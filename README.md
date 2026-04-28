# smart-pdf-splitter

Convert a single, very tall PDF page into a multi-page **US Letter** PDF.

This is **not** a general "split N-page PDF" utility. It targets the specific case of one
extremely tall page (e.g. an exported web article, a long Notion/Confluence page, a tall
infographic) that needs to become printable on Letter paper.

## Splitting rules

The splitter follows two simple rules — everything else flows naturally up to the
page's available height:

1. **Atomic blocks are kept whole.** Images, tables, detected vector
   figures (charts / diagrams / flowcharts), and **callouts** (code blocks,
   admonitions, tip/note boxes — anything sitting inside a filled
   background rectangle) are *never* split across output pages **unless**
   the block itself is taller than a single output page — in which case
   slicing is unavoidable.
2. **Main section headings start a new page.** A heading is "main" when its
   font size is at least `main_heading_size_ratio` × the document's median
   font size (default 1.4×). Subsection headings (smaller bold/large text)
   flow normally with the surrounding text.

Cuts that would slice through a text line are snapped to the nearest safe
gap between lines.

## Features

- The two rules above, and nothing else.
- Vector text and images preserved (`PyMuPDF.show_pdf_page` with clipping).
- Multi-block table detection: tables that PyMuPDF emits as one block per
  cell are merged into a single atomic `TABLE` block before planning.
- Pluggable page sizes: `letter` (default), `legal`, `a4`.
- Configurable margins (per-side, in inches via CLI / points via API).
- Debug artifacts: annotated overlay PDF + PNG showing detected blocks,
  candidate boundaries, and the chosen cut lines, plus a `plan.txt` summary.
- Library API and CLI.

## Installation

```bash
pip install -e .            # runtime deps (PyMuPDF, Pillow)
pip install -e ".[dev]"     # adds pytest + reportlab (used by tests)
```

Python 3.9+.

## CLI usage

```bash
smart-pdf-split input.pdf output.pdf
smart-pdf-split input.pdf output.pdf --debug -v
smart-pdf-split input.pdf output.pdf \
    --page-size letter \
    --margin-top 0.75 --margin-bottom 0.75 \
    --margin-left 0.6 --margin-right 0.6 \
    --debug --debug-dir ./debug
```

Margins are in **inches**. Supported page sizes: `letter` (default), `legal`, `a4`.

## Library usage

```python
from smart_pdf_splitter import SplitConfig, split_pdf

cfg = SplitConfig(debug=True, debug_dir="./debug")
n_pages = split_pdf("input.pdf", "output.pdf", cfg)
```

Customize margins (in PDF points; 72pt = 1 inch) and the main-heading
threshold:

```python
from smart_pdf_splitter import SplitConfig, LETTER

cfg = SplitConfig(
    page_size=LETTER,
    margin_top=54, margin_bottom=54,
    margin_left=36, margin_right=36,
    main_heading_size_ratio=1.4,  # tune to match your document's hierarchy
)
```

## How it works

1. **Extract** — PyMuPDF parses the (single) source page into text blocks,
   lines and spans (with font size & flags), plus image blocks. Vector
   drawings from `page.get_drawings()` are clustered into atomic `FIGURE`
   blocks. Tables that PyMuPDF emits as one block per cell are merged into
   single atomic `TABLE` blocks (multi-block table detection).
2. **Classify** — Each text block whose first line's font size meets the
   `heading_size_ratio` threshold becomes a `HEADING`; if it also meets the
   `main_heading_size_ratio` threshold it becomes a `MAIN_HEADING`. Tables,
   images and figures are flagged as **atomic**.
3. **Candidates** — Generate the small set of cut Y-coordinates: page
   top/bottom, just-before each main heading, and just-around each atomic
   block. Anything inside an atomic block is dropped.
4. **Plan** — Compute `scale = content_width / source_width`, slice
   capacity in source points = `content_height / scale`. Walk top-to-bottom;
   for each output page:

   - If a **main heading** appears inside `[cur, cur+capacity]`, force the
     page to end just above it (the heading then starts the next page).
   - If an **atomic block** of height ≤ capacity straddles the bottom of
     the page, clip the page so the block lands whole on the next page.
   - Otherwise fill the page up to capacity, snapping to the latest gap
     between text lines (so the cut never slices through a line).
5. **Render** — For each slice, create a Letter page and use
   `page.show_pdf_page(target_rect, src_doc, 0, clip=src_rect)` to place
   the clipped region. Vector text/images survive intact; underfill becomes
   natural whitespace at the bottom of the page.

### Atomic-block detection

A block is **atomic** (never split unless taller than a page) when its kind is:

- `IMAGE` — raster image blocks reported directly by PyMuPDF.
- `TABLE` — either a single block whose lines split into multiple x-clusters,
  or (more commonly) several adjacent blocks that PyMuPDF emits as separate
  cells but which form a regular grid of rows and columns. The extractor
  merges these into one `TABLE` block before planning.
- `FIGURE` — a cluster of vector drawings (paths, rectangles, curves)
  detected via `page.get_drawings()`. Tiny strokes (rules / underlines /
  separators) are filtered out, then nearby drawings are merged. Clusters
  that overlap heavily with running text are rejected.
- `CALLOUT` — text sitting inside a filled-background rectangle: fenced
  code blocks, admonitions, tip / note / warning panels, etc. Detected by
  finding sizable non-white filled rects via `page.get_drawings()` and
  swallowing every text block whose bbox sits inside.

Figure detection can be tuned via `SplitConfig`:

```python
SplitConfig(
    detect_figures=True,
    figure_min_height_pt=24.0,
    figure_cluster_gap_ratio=1.5,
)
```

### Heading detection

Heading classification is purely font-size based, relative to the document's
median font size:

| Setting | Default | Meaning |
|---|---|---|
| `heading_size_ratio` | 1.15 | Subsection heading threshold |
| `main_heading_size_ratio` | 1.4 | Main section heading threshold (forces new page) |

Tune `main_heading_size_ratio` if your document uses an unusual heading
hierarchy. Headings are also required to be short (≤ 2 lines, ≤ 120
characters) to avoid mis-classifying long emphasized paragraphs.

## Debug artifacts

When `--debug` is set, the tool writes to `--debug-dir` (or `<output>.debug/`):

- `overlay.pdf` — the source page with colored block boxes (text /
  subsection-heading / **main-heading** / image / table / figure), yellow
  candidate-line markers, and **bold red final cut lines**.
- `overlay.png` — a rasterized version of the same.
- `plan.txt` — page-by-page summary with reasons for each cut.

## Edge cases handled

| Case | Behavior |
|---|---|
| Page rotation set | Normalized to 0° before extraction. |
| Multi-page input | First page only; warning logged. |
| Atomic block (table / image / figure) fits on a page | Always placed in one piece; planner clips the slice early if needed. |
| Atomic block taller than a page | Sliced via the safe geometric path (unavoidable). |
| Main heading near the top of content | Suppressed if within ~50pt of the current page's start (avoids tiny title-only pages). |
| Section taller than one page | Geometric fill in the largest gap between lines. |
| Scanned PDF (no text layer) | Falls back to geometric cuts based on detected images/whitespace; results approximate. |
| Empty top/bottom margins | Trimmed if > 0.5 in of clear empty band. |
| Weird non-Letter source width | Width is scaled to fit Letter content area; aspect preserved. |

## Limitations

- **OCR-less scanned PDFs**: we do not run OCR. Cuts on image-only pages
  are purely geometric.
- **Heading detection** is font-size based; styled-but-not-larger headings
  can be missed. Tune `main_heading_size_ratio` to your document.
- **Multi-column source pages** are detected as overlapping blocks and the
  planner avoids cutting through them, but column-aware reflow is out of
  scope.
- **Vector graphics** are preserved in the render but their bounding boxes
  only influence boundary choice when they are clustered into a `FIGURE`.

## Running tests

```bash
pip install -e ".[dev]"
pytest
```

The tests build synthetic tall PDFs with `reportlab` and verify:
- block & heading extraction,
- candidate ordering / dedup,
- planner coverage and capacity invariants,
- end-to-end Letter-sized output,
- text preservation,
- debug artifact emission,
- **atomic-block protection** (figures and multi-block tables fitting on a
  page are never sliced; figures taller than a page are sliced as a last
  resort),
- **main-heading rule** on the bundled Claude Code Best Practices article
  (every main heading starts a new output page; subsection headings flow
  inline).

## Project layout

```
src/smart_pdf_splitter/
  __init__.py          # public surface
  api.py               # split_pdf()
  cli.py               # `smart-pdf-split`
  config.py            # SplitConfig, page sizes
  models.py            # Block, Line, Span, BoundaryCandidate, Slice, SplitPlan
  extractor.py         # PyMuPDF -> LayoutModel (with multi-block table merging)
  boundary_detection.py# heading classification, candidate generation, geometric fallback
  planner.py           # simplified: main-heading + atomic-block driven splitting
  renderer.py          # writes the multi-page Letter PDF
  debug.py             # overlay PDF / PNG / plan.txt
  logging_config.py    # structured logging
tests/                 # synthetic-PDF tests + real-article regression tests
examples/              # minimal usage scripts
```

## License

MIT.
