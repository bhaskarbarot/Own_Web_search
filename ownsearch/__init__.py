"""OwnSearch: independent direct crawling, indexing and local web retrieval."""
__version__ = "2.0.0"

from .config import Settings
from .coordinator import IndependentSearch
from .tool import search_tool, asearch_tool, SearchResults, OPENAI_TOOL_SCHEMA

__all__ = [
    "__version__",
    "Settings",
    "IndependentSearch",
    "search_tool",
    "asearch_tool",
    "SearchResults",
    "OPENAI_TOOL_SCHEMA"
]
