"""Minimal example: split a tall PDF programmatically."""
from smart_pdf_splitter import SplitConfig, split_pdf

if __name__ == "__main__":
    cfg = SplitConfig(debug=True, debug_dir="./out.debug")
    n = split_pdf("input.pdf", "out.pdf", cfg)
    print(f"Wrote {n} pages")
