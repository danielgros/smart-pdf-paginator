# smart-pdf-splitter

Convert a single, very tall PDF page into a multi-page **US Letter** PDF, splitting at
**semantic boundaries** (before headings, between paragraphs, in whitespace gaps) instead
of slicing through text, tables, or images.

This is **not** a general "split N-page PDF" utility. It targets the specific case of one
extremely tall page (e.g. an exported web article, a long Notion/Confluence page, a tall
infographic) that needs to become printable on Letter paper.

## Features

- Semantic-aware cuts: before headings, after paragraphs, inside large gaps.
- **Atomic block protection**: tables, images, and detected figures (vector
  diagrams / charts / flowcharts) are never split across pages **unless** the
  block itself is taller than a single output page — in which case slicing is
  unavoidable and falls back to the safe geometric path.
- Geometric fallback that still avoids cutting through detected text lines.
- Preserves vector text and images (`PyMuPDF.show_pdf_page` with clipping).
- Adds natural whitespace at the bottom of underfilled pages — never stretches content.
- Pluggable strategies: `semantic`, `visual`, `hybrid` (default).
- Debug artifacts: annotated overlay PDF + PNG showing detected blocks, candidate
  boundaries, and the chosen cut lines, plus a `plan.txt` summary.
- Library API and CLI.
- Type hints, dataclasses, modular components.

## Installation

```bash
pip install -e .            # runtime deps (PyMuPDF, Pillow)
pip install -e ".[dev]"     # adds pytest + reportlab (used by tests)
```

Python 3.9+.

## CLI usage

```bash
smart-pdf-split input.pdf output.pdf
smart-pdf-split input.pdf output.pdf --strategy semantic --debug -v
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

Customize margins (in PDF points; 72pt = 1 inch):

```python
from smart_pdf_splitter import SplitConfig, LETTER

cfg = SplitConfig(
    page_size=LETTER,
    margin_top=54, margin_bottom=54,
    margin_left=36, margin_right=36,
)
```

## How it works

1. **Extract** — PyMuPDF parses the (single) source page into text blocks, lines, spans
   (with font size & flags), and image blocks. Vector drawings from
   `page.get_drawings()` are clustered into atomic `FIGURE` blocks (see below).
2. **Detect** — Heuristics promote large/bold short lines preceded by extra whitespace
   to *headings*. A simple multi-column heuristic flags *table-like* blocks. Tables,
   images, and figures are flagged as **atomic**.
3. **Candidates** — Generate cut Y-coordinates: page top/bottom, just-before-heading,
   just-before/just-after each atomic block, middle of large vertical gaps,
   end-of-paragraph. Any candidate that would land *inside* an atomic block is dropped.
4. **Plan** — Compute `scale = content_width / source_width`, slice capacity in source
   points = `content_height / scale`. Walk top-to-bottom; for each output page:

   - **Atomic-block protection (hard constraint).** If an atomic block of height
     ≤ capacity straddles the current target window, the planner clips the
     window's upper bound to that block's top, forcing the block onto the next
     page in one piece. Atomic blocks taller than capacity are unavoidable and
     fall through to the geometric path.
   - Among remaining candidates inside `[cur, target_max]`, pick the one minimizing:

         cost = semantic_weight * semantic_penalty
              + underfill_weight * underfill² (+ tiny-page penalty)
              + cut_through_weight * (1 if it slices a non-atomic block else 0)

   - If no candidate fits (e.g. one block is taller than a page), fall back to a
     safe geometric cut placed in the largest gap between text lines within the
     window.
5. **Render** — For each slice, create a Letter page and use
   `page.show_pdf_page(target_rect, src_doc, 0, clip=src_rect)` to place the clipped
   region. Vector text/images survive intact; underfill becomes natural whitespace at
   the bottom.

### Atomic-block detection

A block is **atomic** (never split unless taller than a page) when its kind is:

- `IMAGE` — raster image blocks reported directly by PyMuPDF.
- `TABLE` — a sequence of text lines with multiple x-clustered span groups
  (multi-column rows).
- `FIGURE` — a cluster of vector drawings (paths, rectangles, curves) detected
  via `page.get_drawings()`. Tiny strokes (rules / underlines / separators) are
  filtered out, then nearby drawings are merged. Clusters that overlap heavily
  with running text are rejected (they're decorations, not figures).

Figure detection can be tuned via `SplitConfig`:

```python
SplitConfig(
    detect_figures=True,           # disable to skip vector-drawing detection
    figure_min_height_pt=24.0,     # ignore drawing clusters shorter than this
    figure_cluster_gap_ratio=1.5,  # merge drawings within 1.5x median line height
)
```

## Debug artifacts

When `--debug` is set, the tool writes to `--debug-dir` (or `<output>.debug/`):

- `overlay.pdf` — the source page with colored block boxes (text/heading/image/table),
  yellow dashed candidate lines, and **bold red final cut lines**.
- `overlay.png` — a rasterized version of the same.
- `plan.txt` — page-by-page summary with reasons for each cut.

## Edge cases handled

| Case | Behavior |
|---|---|
| Page rotation set | Normalized to 0° before extraction. |
| Multi-page input | First page only; warning logged. |
| Atomic block (table / image / figure) fits on a page | Always placed in one piece; planner clips the slice early if needed. |
| Atomic block taller than a page | Sliced via the safe geometric path (unavoidable). |
| Section taller than one page | Geometric fallback inside largest line gap. |
| Scanned PDF (no text layer) | Falls back to geometric cuts based on detected images/whitespace; results approximate. |
| Empty top/bottom margins | Trimmed if > 0.5 in of clear empty band. |
| Weird non-Letter source width | Width is scaled to fit Letter content area; aspect preserved. |

## Limitations / future improvements

- **OCR-less scanned PDFs**: we do not run OCR. Cuts on image-only pages are purely
  geometric; consider adding an optional Tesseract pass.
- **Table detection** is a coarse heuristic (multi-x-cluster lines). It's used to *avoid*
  cutting through tables but is not authoritative; integrating `pdfplumber.find_tables()`
  would be a clear win.
- **Multi-column source pages** are detected as overlapping blocks and the planner avoids
  cutting through them, but column-aware reflow is out of scope.
- **Vector graphics** are treated as part of the underlying page render — they are
  preserved, but their bounding boxes don't influence boundary choice.
- **Heading detection** is font/size/spacing-based; styled-but-not-larger headings can
  be missed. A learned classifier would be more robust.
- **Dynamic-programming planner** would marginally outperform the current greedy-with-
  lookahead in pathological inputs.

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
- **atomic-block protection** (figures fitting on a page are never sliced;
  figures taller than a page are sliced as a last resort).

## Project layout

```
src/smart_pdf_splitter/
  __init__.py          # public surface
  api.py               # split_pdf()
  cli.py               # `smart-pdf-split`
  config.py            # SplitConfig, page sizes, strategies
  models.py            # Block, Line, Span, BoundaryCandidate, Slice, SplitPlan
  extractor.py         # PyMuPDF -> LayoutModel
  boundary_detection.py# heading classification, candidate generation, geometric fallback
  planner.py           # greedy-with-lookahead cut selection
  renderer.py          # writes the multi-page Letter PDF
  debug.py             # overlay PDF / PNG / plan.txt
  logging_config.py    # structured logging
tests/                 # synthetic-PDF tests (reportlab)
examples/              # minimal usage scripts
```

## License

MIT.
