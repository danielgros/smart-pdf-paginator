"""Smart PDF splitter: turn one tall PDF page into many US Letter pages."""
from .config import SplitConfig, Strategy, PageSize, LETTER
from .api import split_pdf

__all__ = ["SplitConfig", "Strategy", "PageSize", "LETTER", "split_pdf"]
__version__ = "0.1.0"
