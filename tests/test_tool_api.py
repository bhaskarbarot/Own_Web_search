"""Unit tests for public agent API: search_tool, asearch_tool, SearchResults, PDF export, and MCP server."""
import asyncio
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ownsearch.tool import search_tool, asearch_tool, SearchResults, OPENAI_TOOL_SCHEMA
from ownsearch.pdf_export import generate_pdf
from ownsearch.coordinator import IndependentSearch
from tests.independent_fixture import Site, article
from tests.test_independent import settings

class ToolApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.site = Site()

    @classmethod
    def tearDownClass(cls):
        cls.site.close()

    def test_search_tool_basic_and_properties(self):
        engine = IndependentSearch(settings(max_pages_per_query=1))
        res = search_tool('orbital guidance', seeds=[self.site.base + '/guide'], engine=engine)
        self.assertIsInstance(res, SearchResults)
        self.assertIn("orbital guidance", res.query)
        self.assertTrue(len(res.results) > 0)
        self.assertIn(self.site.base + '/guide', res.text)
        self.assertIn(self.site.base + '/guide', res.to_markdown())
        self.assertEqual(res.to_dict()['query'], res.raw['query'])
        self.assertEqual(res.json()['mode'], 'independent')

    def test_search_tool_with_filters(self):
        engine = IndependentSearch(settings(max_pages_per_query=2))
        res = search_tool(
            'orbital',
            max_results=3,
            sites=['example.org'],
            exact_phrase='guidance',
            exclude_terms=['wrongterm'],
            freshness='year',
            file_types=['html'],
            engine=engine,
            seeds=[self.site.base + '/guide']
        )
        self.assertIsInstance(res, SearchResults)

    def test_search_tool_pdf_export(self):
        engine = IndependentSearch(settings(max_pages_per_query=1))
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / 'results.pdf'
            res = search_tool(
                'orbital guidance',
                seeds=[self.site.base + '/guide'],
                export=str(pdf_path),
                engine=engine
            )
            self.assertTrue(pdf_path.exists())
            data = pdf_path.read_bytes()
            self.assertTrue(data.startswith(b'%PDF-1.4'))
            self.assertTrue(data.endswith(b'%%EOF\n'))

    def test_asearch_tool_async(self):
        engine = IndependentSearch(settings(max_pages_per_query=1))
        async def run():
            return await asearch_tool('orbital guidance', seeds=[self.site.base + '/guide'], engine=engine)
        res = asyncio.run(run())
        self.assertIsInstance(res, SearchResults)
        self.assertTrue(len(res.results) > 0)

    def test_mcp_server_protocol(self):
        """Test MCP JSON-RPC protocol over stdio."""
        cmd = [sys.executable, '-m', 'ownsearch.mcp']
        init_req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        tools_req = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        input_data = f"{init_req}\n{tools_req}\n"

        p = subprocess.run(cmd, input=input_data, text=True, capture_output=True, timeout=10)
        self.assertEqual(p.returncode, 0)
        lines = [json.loads(line) for line in p.stdout.strip().splitlines() if line.strip()]
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0]['id'], 1)
        self.assertEqual(lines[0]['result']['serverInfo']['name'], 'ownsearch')
        self.assertEqual(lines[1]['id'], 2)
        tools = lines[1]['result']['tools']
        self.assertEqual(tools[0]['name'], 'search')

    def test_search_tool_output_formats(self):
        engine = IndependentSearch(settings(max_pages_per_query=1))
        # Test output="markdown" (Firecrawl style)
        md = search_tool('orbital guidance', seeds=[self.site.base + '/guide'], output='markdown', engine=engine)
        self.assertIsInstance(md, str)
        self.assertIn("Title:", md)
        self.assertIn("URL:", md)
        self.assertIn(self.site.base + '/guide', md)

        # Test output="text"
        txt = search_tool('orbital guidance', seeds=[self.site.base + '/guide'], output='text', engine=engine)
        self.assertIsInstance(txt, str)
        self.assertIn(self.site.base + '/guide', txt)

        # Test output="json"
        js = search_tool('orbital guidance', seeds=[self.site.base + '/guide'], output='json', engine=engine)
        self.assertIsInstance(js, dict)
        self.assertEqual(js['mode'], 'independent')

    def test_code_and_lead_summary_answer(self):
        from ownsearch.evidence import extract_code_answer, extract_lead_summary
        from ownsearch.webmodels import WebCandidate

        cand = WebCandidate(
            title="Python Palindrome Program",
            url="https://example.org/palindrome",
            content="A palindrome string is a string that reads the same backwards and forwards. For example, radar or noon are palindromes. In Python, checking a palindrome can be done using slicing or reversed string functions.",
            code_blocks=[{
                "code": "def is_palindrome(s):\n    return s == s[::-1]",
                "language": "python",
                "heading": "Using Slicing"
            }]
        )

        code_ans = extract_code_answer(cand, query_terms=["palindrome", "code", "python"], query="how to write palindrome code in python")
        self.assertIsNotNone(code_ans)
        self.assertEqual(code_ans["type"], "code")
        self.assertEqual(code_ans["language"], "python")
        self.assertIn("return s == s[::-1]", code_ans["code"])
        self.assertEqual(code_ans["citations"][0]["url"], "https://example.org/palindrome")

        # Knowledge / Lead Summary test
        gandhi_cand = WebCandidate(
            title="Mahatma Gandhi - Wikipedia",
            url="https://en.wikipedia.org/wiki/Mahatma_Gandhi",
            content="Mohandas Karamchand Gandhi was an Indian lawyer, anti-colonial nationalist and political ethicist who employed nonviolent resistance to lead the successful campaign for India's independence from British rule. He inspired movements for civil rights and freedom across the world."
        )
        lead_ans = extract_lead_summary(gandhi_cand, query_terms=["gandhiji", "who"])
        self.assertIsNotNone(lead_ans)
        self.assertEqual(lead_ans["type"], "summary")
        self.assertIn("Mohandas Karamchand Gandhi was an Indian lawyer", lead_ans["text"])
        self.assertIn("anti-colonial nationalist", lead_ans["text"])


if __name__ == '__main__':
    unittest.main()
