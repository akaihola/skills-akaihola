#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp"]
# ///
"""
MCP Skill Executor
==================
Handles dynamic communication with the MCP server.
"""

import asyncio
import argparse
import json
import sys
from pathlib import Path

# Import mcp package
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class MCPExecutor:
    """Execute MCP tool calls dynamically."""

    def __init__(self, server_config):
        self.server_config = server_config

    def _get_server_params(self):
        """Get server parameters for connection."""
        return StdioServerParameters(
            command=self.server_config["command"],
            args=self.server_config.get("args", []),
            env=self.server_config.get("env")
        )

    async def list_tools(self):
        """Get list of available tools."""
        server_params = self._get_server_params()

        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                response = await session.list_tools()
                return [
                    {
                        "name": tool.name,
                        "description": tool.description
                    }
                    for tool in response.tools
                ]

    async def describe_tool(self, tool_name: str):
        """Get detailed schema for a specific tool."""
        server_params = self._get_server_params()

        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                response = await session.list_tools()
                for tool in response.tools:
                    if tool.name == tool_name:
                        return {
                            "name": tool.name,
                            "description": tool.description,
                            "inputSchema": tool.inputSchema
                        }
                return None

    async def call_tool(self, tool_name: str, arguments: dict):
        """Execute a tool call."""
        server_params = self._get_server_params()

        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                response = await session.call_tool(tool_name, arguments)
                return response.content


async def main():
    parser = argparse.ArgumentParser(description="MCP Skill Executor")
    parser.add_argument("--call", help="JSON tool call to execute")
    parser.add_argument("--describe", help="Get tool schema")
    parser.add_argument("--list", action="store_true", help="List all tools")

    args = parser.parse_args()

    # Load server config
    config_path = Path(__file__).parent / "mcp-config.json"
    if not config_path.exists():
        print(f"Error: Configuration file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    with open(config_path) as f:
        config = json.load(f)

    executor = MCPExecutor(config)

    try:
        if args.list:
            tools = await executor.list_tools()
            print(json.dumps(tools, indent=2))

        elif args.describe:
            schema = await executor.describe_tool(args.describe)
            if schema:
                print(json.dumps(schema, indent=2))
            else:
                print(f"Tool not found: {args.describe}", file=sys.stderr)
                sys.exit(1)

        elif args.call:
            call_data = json.loads(args.call)
            result = await executor.call_tool(
                call_data["tool"],
                call_data.get("arguments", {})
            )

            # Format result
            if isinstance(result, list):
                for item in result:
                    if hasattr(item, 'text'):
                        print(item.text)
                    else:
                        print(json.dumps(item.__dict__ if hasattr(item, '__dict__') else item, indent=2))
            else:
                print(json.dumps(result.__dict__ if hasattr(result, '__dict__') else result, indent=2))
        else:
            parser.print_help()

    except Exception as e:
        print(f"Error: {str(e)}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
