"""Public search_tool and asearch_tool API for AI agents and Python applications."""
import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .config import Settings
from .coordinator import IndependentSearch
from .pdf_export import generate_pdf

_DEFAULT_ENGINE = None

def get_engine() -> IndependentSearch:
    global _DEFAULT_ENGINE
    if _DEFAULT_ENGINE is None:
        _DEFAULT_ENGINE = IndependentSearch(Settings.load())
    return _DEFAULT_ENGINE

class SearchResults:
    def __init__(self, raw: Dict[str, Any]):
        self.raw = raw
        self.query = raw.get('query', '')
        self.results = raw.get('results', [])
        self.answer = raw.get('answer')
        self.images = raw.get('images', [])
        self.took_ms = raw.get('took_ms', 0.0)
        self.cached = raw.get('cached', False)
        self.coverage = raw.get('coverage', {})
        self.limitations = raw.get('limitations', [])

    @property
    def text(self) -> str:
        """Formatted human-readable and LLM-friendly text with links and citations."""
        lines = []
        if self.answer:
            lines.append(f"Answer: {self.answer.get('text', '')}")
            citations = self.answer.get('citations', [])
            if citations:
                c_str = ", ".join(f"[{c.get('title', 'link')}]({c.get('url', '')})" for c in citations)
                lines.append(f"Sources: {c_str}")
            if self.answer.get('disclaimer'):
                lines.append(f"Note: {self.answer['disclaimer']}")
            lines.append("")

        if self.results:
            lines.append(f"Results for '{self.query}':\n")
            for r in self.results:
                rank = r.get('rank', '')
                title = r.get('title', '')
                url = r.get('url', '')
                snippet = r.get('snippet', '')
                lines.append(f"{rank}. [{title}]({url})")
                if snippet:
                    lines.append(f"   {snippet}")
                meta = []
                if r.get('published_at'):
                    meta.append(f"Date: {r['published_at']}")
                if r.get('filetype'):
                    meta.append(f"Type: {r['filetype']}")
                if meta:
                    lines.append(f"   ({' · '.join(meta)})")
                lines.append("")
        else:
            lines.append(f"No results found for '{self.query}'.")

        return "\n".join(lines).strip()

    def to_markdown(self) -> str:
        return self.text

    def to_dict(self) -> Dict[str, Any]:
        return self.raw

    def json(self) -> Dict[str, Any]:
        return self.raw

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.raw, indent=indent, ensure_ascii=False)

    def to_pdf(self, path: Union[str, Path]) -> bytes:
        """Export search results to a PDF file."""
        sections = []
        if self.answer:
            sections.append(("Direct Answer", self.answer.get('text', ''), ""))
        for r in self.results:
            sections.append((f"{r.get('rank', '')}. {r.get('title', '')}", r.get('snippet', ''), r.get('url', '')))
        return generate_pdf(f"Search Results: {self.query}", sections, output_path=path)

    def __str__(self) -> str:
        return self.text

    def __repr__(self) -> str:
        return f"<SearchResults query='{self.query}' results={len(self.results)} took={self.took_ms}ms>"


def search_tool(
    query: str,
    max_results: int = 5,
    sites: Optional[List[str]] = None,
    exclude_sites: Optional[List[str]] = None,
    content_type: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    freshness: Optional[str] = None,
    language: Optional[str] = None,
    file_types: Optional[List[str]] = None,
    exact_phrase: Optional[str] = None,
    exclude_terms: Optional[List[str]] = None,
    time_budget_s: Optional[float] = None,
    use_cache: bool = True,
    cache_ttl: Optional[Union[str, float]] = None,
    output: str = "text",
    include_passages: bool = True,
    include_images: bool = False,
    export: Optional[str] = None,
    engine: Optional[IndependentSearch] = None,
    **extra
) -> Union[SearchResults, str, Dict[str, Any]]:
    """Clean, high-level search tool for AI agents and developers."""
    eng = engine or get_engine()

    # Construct synthesized query
    q_parts = [query]
    if exact_phrase:
        q_parts.append(f'"{exact_phrase}"')
    if exclude_terms:
        for term in exclude_terms:
            q_parts.append(f'-{term}')
    if exclude_sites:
        for s in exclude_sites:
            q_parts.append(f'-site:{s}')
    if date_from:
        q_parts.append(f'after:{date_from}')
    if date_to:
        q_parts.append(f'before:{date_to}')

    full_query = " ".join(q_parts).strip()

    search_type = 'web'
    if content_type == 'image' or include_images:
        search_type = 'images'
    elif content_type == 'video':
        search_type = 'video'

    # Map file_types
    ft_str = ",".join(file_types) if file_types else None
    if content_type == 'pdf' and not ft_str:
        ft_str = 'pdf'

    timeout_ms = int(time_budget_s * 1000) if time_budget_s is not None else None
    site_str = ",".join(sites) if sites else None

    raw_res = eng.search(
        query=full_query,
        limit=max_results,
        freshness=freshness if freshness != 'any' else None,
        site=site_str,
        filetype=ft_str,
        lang=language,
        timeout_ms=timeout_ms,
        use_cache=use_cache,
        search_type=search_type,
        answer_mode=True,
        explain=False,
        **extra
    )

    results_obj = SearchResults(raw_res)

    if export:
        if export.lower().endswith('.pdf'):
            results_obj.to_pdf(export)
        elif export.lower().endswith('.json'):
            Path(export).write_text(results_obj.to_json())
        elif export.lower().endswith('.md'):
            Path(export).write_text(results_obj.to_markdown())

    if output == 'json':
        return results_obj.to_dict()
    elif output == 'markdown':
        return results_obj.to_markdown()
    return results_obj


async def asearch_tool(*args, **kwargs):
    """Async wrapper for search_tool."""
    return await asyncio.to_thread(search_tool, *args, **kwargs)


OPENAI_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "search_tool",
        "description": "Search the live web independently for real-time information, documentation, news, facts, and citations without paid search APIs.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query, optionally including search operators (site:example.org, filetype:pdf, \"exact phrase\", -exclusion)."
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of ranked results to return (1 to 50). Default is 5.",
                    "default": 5
                },
                "sites": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter results to specific domains (e.g. ['docs.python.org'])."
                },
                "content_type": {
                    "type": "string",
                    "enum": ["general", "docs", "news", "code", "pdf", "image", "video"],
                    "description": "Content classification filter."
                },
                "freshness": {
                    "type": "string",
                    "enum": ["any", "day", "week", "month", "year"],
                    "description": "Filter results by publication date freshness."
                },
                "file_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "File extensions to filter for (e.g. ['pdf', 'docx', 'xlsx', 'csv'])."
                }
            },
            "required": ["query"]
        }
    }
}
