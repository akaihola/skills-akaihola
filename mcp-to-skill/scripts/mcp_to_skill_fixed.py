#!/usr/bin/env python3
"""
MCP to Skill Converter
======================
Converts any MCP server into a Claude Skill with dynamic tool invocation.

This implements the "progressive disclosure" pattern:
- At startup: Only skill metadata is loaded (~100 tokens)
- On use: Full tool list and instructions are loaded (~5k tokens)
- On execution: Tools are called dynamically (0 context tokens)

Usage:
    python mcp_to_skill.py --mcp-config mcp-server-config.json --output-dir ./skills/my-mcp-skill
"""

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

# Import mcp package
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class MCPSkillGenerator:
    """Generate a Skill from an MCP server configuration."""

    def __init__(self, mcp_config: Dict[str, Any], output_dir: Path):
        self.mcp_config = mcp_config
        self.output_dir = Path(output_dir)
        self.server_name = mcp_config.get("name", "unnamed-mcp-server")

    async def generate(self):
        """Generate the complete skill structure."""
        self.output_dir.mkdir(parents=True, exist_ok=True)

        print(f"Generating skill for MCP server: {self.server_name}")

        # 1. Introspect MCP server to get tool list
        tools = await self._get_mcp_tools()

        # 2. Generate SKILL.md
        self._generate_skill_md(tools)

        # 3. Generate executor script
        self._generate_executor()

        # 4. Generate config file
        self._generate_config()

        # 5. Generate package.json (if needed)
        self._generate_package_json()

        print(f"✓ Skill generated at: {self.output_dir}")
        print(f"✓ Tools available: {len(tools)}")

    async def _get_mcp_tools(self) -> List[Dict[str, Any]]:
        """Connect to MCP server and get available tools."""
        command = self.mcp_config.get("command", "")

        print(f"Introspecting MCP server: {command}")

        # Connect to the actual MCP server
        try:
            server_params = StdioServerParameters(
                command=self.mcp_config["command"],
                args=self.mcp_config.get("args", []),
                env=self.mcp_config.get("env"),
            )

            async with stdio_client(server_params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    response = await session.list_tools()

                    tools = []
                    for tool in response.tools:
                        tools.append(
                            {
                                "name": tool.name,
                                "description": tool.description,
                                "inputSchema": tool.inputSchema,
                            }
                        )

                    return tools
        except Exception as e:
            print(f"Error connecting to MCP server: {e}", file=sys.stderr)
            raise e

    def _generate_skill_md(self, tools: List[Dict[str, Any]]):
        """Generate the SKILL.md file with instructions for Claude."""

        # Create tool list for Claude
        tool_list = ""
        for tool in tools:
            name = tool["name"]
            description = tool.get("description", "No description")
            tool_list += f"- `{name}`: {description}\n"

        # Count tools
        tool_count = len(tools)
        estimated_tokens = tool_count * 500
        first_tool_name = tools[0]["name"] if tools else "tool_name"
        savings_percentage = (
            int((1 - 5000 / (tool_count * 500)) * 100) if tool_count > 0 else 0
        )

        # Load SKILL.md template
        # The templates are in the mcp-to-skill directory relative to the project root
        script_dir = Path(__file__).parent
        project_root = script_dir.parent.parent
        template_path = (
            project_root / "mcp-to-skill" / "assets" / "templates" / "SKILL.md.template"
        )
        with open(template_path, "r") as f:
            template_content = f.read()

        # Format template
        content = template_content.format(
            server_name=self.server_name,
            tool_count=tool_count,
            estimated_tokens=estimated_tokens,
            tool_list=tool_list,
            first_tool_name=first_tool_name,
            savings_percentage=savings_percentage,
        )

        skill_path = self.output_dir / "SKILL.md"
        skill_path.write_text(content)
        print(f"✓ Generated: {skill_path}")

    def _generate_executor(self):
        """Generate the executor script that communicates with MCP server."""

        # Load executor.py template
        # The templates are in the mcp-to-skill directory relative to the project root
        script_dir = Path(__file__).parent
        project_root = script_dir.parent.parent
        template_path = (
            project_root
            / "mcp-to-skill"
            / "assets"
            / "templates"
            / "executor.py.template"
        )
        with open(template_path, "r") as f:
            executor_code = f.read()

        executor_path = self.output_dir / "executor.py"
        executor_path.write_text(executor_code)
        executor_path.chmod(0o755)
        print(f"✓ Generated: {executor_path}")

    def _generate_config(self):
        """Save MCP server config for the executor."""
        config_path = self.output_dir / "mcp-config.json"
        with open(config_path, "w") as f:
            json.dump(self.mcp_config, f, indent=2)
        print(f"✓ Generated: {config_path}")

    def _generate_package_json(self):
        """Generate package.json for dependencies."""
        package = {
            "name": f"skill-{self.server_name}",
            "version": "1.0.0",
            "description": f"Claude Skill wrapper for {self.server_name} MCP server",
            "scripts": {"setup": "pip install mcp"},
        }

        package_path = self.output_dir / "package.json"
        with open(package_path, "w") as f:
            json.dump(package, f, indent=2)
        print(f"✓ Generated: {package_path}")


async def convert_mcp_to_skill(mcp_config_path: str, output_dir: str):
    """Convert an MCP server configuration to a Skill."""

    # Load MCP config
    with open(mcp_config_path) as f:
        mcp_config = json.load(f)

    # Generate skill
    generator = MCPSkillGenerator(mcp_config, Path(output_dir))
    await generator.generate()

    print("\n" + "=" * 60)
    print("✓ Skill generation complete!")
    print("=" * 60)
    print(f"\nGenerated files:")
    print(f"  - SKILL.md (instructions for Claude)")
    print(f"  - executor.py (MCP communication handler)")
    print(f"  - mcp-config.json (MCP server configuration)")
    print(f"  - package.json (dependencies)")

    print(f"\nTo use this skill:")
    print(f"1. Install dependencies:")
    print(f"   cd {output_dir}")
    print(f"   pip install mcp")
    print(f"\n2. Copy to Claude skills directory:")
    print(f"   cp -r {output_dir} ~/.claude/skills/")
    print(f"\n3. Claude will discover it automatically")

    print(f"\nContext savings:")
    print(f"  Before (MCP): All tools preloaded (~10k-50k tokens)")
    print(f"  After (Skill): ~100 tokens until used")
    print(f"  Reduction: ~90-99%")


def main():
    parser = argparse.ArgumentParser(
        description="Convert MCP server to Claude Skill with progressive disclosure",
        epilog="Example: python mcp_to_skill.py --mcp-config github-mcp.json --output-dir ./skills/github",
    )
    parser.add_argument(
        "--mcp-config", required=True, help="Path to MCP server configuration JSON"
    )
    parser.add_argument(
        "--output-dir", required=True, help="Output directory for generated skill"
    )

    args = parser.parse_args()

    asyncio.run(convert_mcp_to_skill(args.mcp_config, args.output_dir))


if __name__ == "__main__":
    main()
