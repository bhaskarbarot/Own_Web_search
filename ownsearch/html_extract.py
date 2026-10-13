"""Backwards-compatible import path (v0.1). The extractor now lives in ownsearch.extract.html."""
from .extract.html import extract_html

__all__ = ["extract_html"]
