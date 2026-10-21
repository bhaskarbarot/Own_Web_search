"""Model Context Protocol (MCP) server for OwnSearch over stdio."""
import json
import sys
from .tool import search_tool, OPENAI_TOOL_SCHEMA

def run_mcp_server():
    """Run MCP JSON-RPC server listening on stdin/stdout."""
    tool_schema = OPENAI_TOOL_SCHEMA["function"]["parameters"]
    tools_list = [
        {
            "name": "search",
            "description": "Search the live web independently for real-time information, documentation, news, facts, and citations without paid search APIs.",
            "inputSchema": tool_schema
        }
    ]

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            continue

        req_id = req.get("id")
        method = req.get("method")
        params = req.get("params", {})

        if method == "initialize":
            res = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "ownsearch", "version": "2.0.0"}
                }
            }
        elif method == "notifications/initialized":
            continue
        elif method == "ping":
            res = {"jsonrpc": "2.0", "id": req_id, "result": {}}
        elif method == "tools/list":
            res = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": tools_list}
            }
        elif method == "tools/call":
            tool_name = params.get("name")
            args = params.get("arguments", {})
            if tool_name == "search":
                try:
                    out = search_tool(**args)
                    text = out.text if hasattr(out, 'text') else str(out)
                    res = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [{"type": "text", "text": text}],
                            "isError": False
                        }
                    }
                except Exception as e:
                    res = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [{"type": "text", "text": f"Search failed: {e}"}],
                            "isError": True
                        }
                    }
            else:
                res = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Tool '{tool_name}' not found"}
                }
        else:
            if req_id is not None:
                res = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Method '{method}' not found"}
                }
            else:
                continue

        sys.stdout.write(json.dumps(res, ensure_ascii=False) + "\n")
        sys.stdout.flush()

if __name__ == '__main__':
    run_mcp_server()
