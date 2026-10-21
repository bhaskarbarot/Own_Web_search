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

if __name__ == '__main__':
    unittest.main()
