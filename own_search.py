"""own_search module alias for ownsearch package."""
from ownsearch import (
    __version__,
    Settings,
    IndependentSearch,
    search_tool,
    asearch_tool,
    SearchResults,
    OPENAI_TOOL_SCHEMA,
)

__all__ = [
    "__version__",
    "Settings",
    "IndependentSearch",
    "search_tool",
    "asearch_tool",
    "SearchResults",
    "OPENAI_TOOL_SCHEMA",
]
