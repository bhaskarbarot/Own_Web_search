# Phase Plan: Firecrawl-Grade Markdown, Direct Code/Answer Extraction & Agent Tool Pipeline

Date: 2026-10-22, Asia/Kolkata.
Branch: `Independent`.

## 1. Goal

Transform OwnSearch from returning plain 160-character truncated link snippets into a Firecrawl- and DuckDuckGo-grade AI-agent web search engine that:
1. Directly answers queries with substantive content:
   - For coding queries (e.g. `how to write palindrome code in python`), extracts and presents the actual functional code block (` ```python ... ``` `), not just documentation links.
   - For knowledge/entity queries (e.g. `who is gandhiji`), extracts a comprehensive lead summary from authoritative pages, followed by relevant citations.
2. Generates structured Markdown (`# Heading`, `## Section`, ` ```code``` `, clean lists) for fetched pages, matching the Firecrawl Search API schema.
3. Enhances the pip-installable Python API (`from ownsearch import search_tool`) with first-class agent output modes: `output="text"`, `output="code"`, `output="markdown"`, `output="json"`.
4. Upgrades the Web UI answer card to display dedicated code blocks with monospaced styling and a 1-click "Copy Code" button, and rich markdown rendering in result snippets.
5. Expands 80/20 algorithm hubs in `sources.txt` to cover programming algorithm queries (GeeksforGeeks, Programiz, Real Python, W3Schools, Britannica).

## 2. Files to Change

1. `ownsearch/extract/html.py`:
   - Add semantic Markdown generator that preserves headings (`# `, `## `), lists (`- `), and fenced code blocks (```python ... ```) with indentation and newlines.
   - Extract raw `<pre><code>` blocks with detected language and surrounding context.
   - Populate `markdown` and `code_blocks` in the extraction dictionary.
2. `ownsearch/webmodels.py`:
   - Add `markdown: str = ''` and `code_blocks: list = field(default_factory=list)` to `WebCandidate`.
   - Include `markdown` and `code_blocks` in the result dictionary.
3. `ownsearch/evidence.py`:
   - Add `extract_code_answer(candidate, query)`: scores candidate code blocks against query terms and extracts the best functional code.
   - Add `extract_lead_summary(candidate, query)`: extracts full lead introductory paragraphs (300-800 characters) for entities and definitions without mid-word truncation.
4. `ownsearch/coordinator.py`:
   - Incorporate code and lead summary answer extraction when `answer_mode` is enabled.
   - Detect coding intent (`q.intent == "tech_docs"` or query contains keywords like `code`, `python`, `function`, `program`, `algorithm`, `how to write`).
   - Add slug generation for programming examples on coding hubs.
5. `sources.txt`:
   - Add curated hubs for programming tutorials and algorithms: GeeksforGeeks, Programiz, Real Python, W3Schools, Britannica.
6. `ownsearch/tool.py` & `ownsearch/cli.py`:
   - Support `output="text"`, `output="code"`, `output="markdown"`, `output="json"`.
   - Update `SearchResults` with Firecrawl-style `to_markdown()`, `code`, and clean `text`.
   - Add `--format` / `-f` (`text`, `code`, `markdown`, `json`) to CLI.
7. `ownsearch/resources/search.html`:
   - Update `showAnswer()`: if `answer.type === 'code'`, render a styled `<pre><code>` container with a "Copy Code" button.
   - Render multi-paragraph lead summaries cleanly.
8. `tests/`:
   - Unit tests for markdown extraction, code block preservation, answer generation, and `search_tool` agent formats.

## 3. Ordered Steps

- **Step 1: HTML-to-Markdown & Code Block Extractor (`ownsearch/extract/html.py`, `ownsearch/webmodels.py`)**
  - Implement `<pre><code>` block tracking in `_Parser`, preserving exact code indentation and line breaks.
  - Generate structured markdown with `# ` headings and fenced code blocks.
  - Pass `markdown` and `code_blocks` through `WebCandidate`.
  - Measure: verify `<pre><code>` preserves newlines and indentations; run test suite.

- **Step 2: Direct Code & Lead Summary Answer Extraction (`ownsearch/evidence.py`, `ownsearch/coordinator.py`)**
  - Build `extract_code_answer()` and `extract_lead_summary()`.
  - Wire into query execution so coding queries return the code block as `answer = {'type': 'code', 'code': '...', 'language': 'python', ...}`.
  - Wire knowledge queries to return full lead summaries.
  - Measure: unit tests for answer generation; verify `who is gandhiji` and `palindrome code`.

- **Step 3: Hub Expansion & Algorithm Path Resolution (`sources.txt`, `ownsearch/coordinator.py`)**
  - Add standard coding tutorial hubs in `sources.txt`.
  - Enable candidate slug generation for programming examples (e.g. `python-program-check-string-palindrome-not`).
  - Measure: crawler and coordinator tests.

- **Step 4: AI Agent Tool Output Modes & CLI (`ownsearch/tool.py`, `ownsearch/cli.py`)**
  - Implement Firecrawl-style markdown output in `SearchResults.to_markdown()`.
  - Implement `output="code"` and `output="text"`.
  - Support `--format` in CLI.
  - Measure: test `search_tool(query, output="code")` and `search_tool(query, output="markdown")`.

- **Step 5: Modern UI Answer Card & Code Display (`ownsearch/resources/search.html`)**
  - Add code card styling (monospaced font, dark background, copy-to-clipboard button).
  - Add markdown formatting for lead paragraphs.
  - Measure: visual and headless browser validation.

- **Step 6: End-to-End Benchmark & Handoff**
  - Run full test suite (147+ tests in standard Python and `python3 -S`).
  - Update `docs/PROGRESS.md`.
