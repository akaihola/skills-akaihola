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
    python scripts/convert_mcp_to_skill.py --mcp-config mcp-server-config.json --output-dir ./skills/my-mcp-skill
"""

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional


class MCPSkillGenerator:
    """Generate a Skill from an MCP server configuration."""

    def __init__(self, mcp_config: Dict[str, Any], output_dir: Path):
        self.mcp_config = mcp_config
        self.output_dir = Path(output_dir)
        self.server_name = mcp_config.get("name", "unnamed-mcp-server")
        self.converter_url = "https://raw.githubusercontent.com/GBSOSS/-mcp-to-skill-converter/main/mcp_to_skill.py"

    async def generate(self):
        """Generate the complete skill structure."""
        self.output_dir.mkdir(parents=True, exist_ok=True)

        print(f"Generating skill for MCP server: {self.server_name}")

        # 1. Download the latest converter script
        await self._download_converter()

        # 2. Run the converter to generate the skill
        await self._run_converter()

        # 3. Add additional documentation
        self._add_documentation()

        # 4. Add example usage
        self._add_examples()

        print(f"✓ Skill generated at: {self.output_dir}")

    async def _download_converter(self):
        """Download the latest mcp_to_skill.py converter."""
        print("Downloading latest converter script...")

        try:
            with urllib.request.urlopen(self.converter_url) as response:
                converter_script = response.read().decode("utf-8")

            converter_path = self.output_dir / "mcp_to_skill.py"
            with open(converter_path, "w") as f:
                f.write(converter_script)

            converter_path.chmod(0o755)  # Make executable
            print(f"✓ Downloaded converter to: {converter_path}")

        except Exception as e:
            print(f"Error downloading converter: {e}")
            sys.exit(1)

    async def _run_converter(self):
        """Run the downloaded converter script."""
        print("Running converter script...")

        # Create a temporary config file
        temp_config_path = self.output_dir / "temp_mcp_config.json"
        with open(temp_config_path, "w") as f:
            json.dump(self.mcp_config, f, indent=2)

        # Run the converter
        try:
            cmd = [
                sys.executable,
                str(self.output_dir / "mcp_to_skill.py"),
                "--mcp-config",
                str(temp_config_path),
                "--output-dir",
                str(self.output_dir / "generated_skill"),
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            print(result.stdout)

            # Move the generated skill to the output directory
            generated_skill_dir = self.output_dir / "generated_skill"
            if generated_skill_dir.exists():
                for item in generated_skill_dir.iterdir():
                    dest = self.output_dir / item.name
                    if dest.exists():
                        if dest.is_dir():
                            shutil.rmtree(dest)
                        else:
                            dest.unlink()
                    shutil.move(str(item), str(dest))
                shutil.rmtree(generated_skill_dir)

            # Clean up temp config
            temp_config_path.unlink()

        except subprocess.CalledProcessError as e:
            print(f"Error running converter: {e}")
            print(f"Stdout: {e.stdout}")
            print(f"Stderr: {e.stderr}")
            sys.exit(1)

    def _add_documentation(self):
        """Add additional documentation to the generated skill."""
        docs_dir = self.output_dir / "docs"
        docs_dir.mkdir(exist_ok=True)

        # Create a README with usage instructions
        readme_content = f"""# {self.server_name} Skill

This skill was generated from an MCP server configuration using the mcp-to-skill converter.

## Installation

1. Install dependencies:
```bash
pip install mcp
```

2. The skill is ready to use with Claude.

## Usage

Claude will automatically discover this skill and use it when appropriate.

## Testing

You can test the skill directly:

```bash
# List available tools
python executor.py --list

# Get details about a specific tool
python executor.py --describe tool_name

# Call a tool
python executor.py --call '{{"tool": "tool_name", "arguments": {{"param": "value"}}}}'
```

## Configuration

The MCP server configuration is stored in `mcp-config.json`.

## Context Savings

This skill provides significant context savings compared to using the MCP server directly:
- Idle: ~100 tokens vs ~{len(self.mcp_config.get('tools', [])) * 500} tokens
- Active: ~5k tokens vs ~{len(self.mcp_config.get('tools', [])) * 500} tokens
"""

        readme_path = self.output_dir / "README.md"
        with open(readme_path, "w") as f:
            f.write(readme_content)

        print(f"✓ Added documentation: {readme_path}")

    def _add_examples(self):
        """Add example usage files."""
        examples_dir = self.output_dir / "examples"
        examples_dir.mkdir(exist_ok=True)

        # Create a simple test script
        test_script_content = "#!/usr/bin/env python3\n"
        test_script_content += '"""\nTest script for generated skill\n"""\n\n'
        test_script_content += "import json\n"
        test_script_content += "import subprocess\n"
        test_script_content += "import sys\n\n"
        test_script_content += "def run_command(cmd):\n"
        test_script_content += '    """Run a command and return the result."""\n'
        test_script_content += "    try:\n"
        test_script_content += "        result = subprocess.run(cmd, capture_output=True, text=True, check=True)\n"
        test_script_content += "        return result.stdout\n"
        test_script_content += "    except subprocess.CalledProcessError as e:\n"
        test_script_content += '        return f"Error: {e.stderr}"\n\n'
        test_script_content += "def main():\n"
        test_script_content += '    """Test the generated skill."""\n'
        test_script_content += '    print("Testing generated skill...")\n\n'
        test_script_content += "    # Test listing tools\n"
        test_script_content += '    print("\\n1. Listing available tools:")\n'
        test_script_content += '    tools_output = run_command([sys.executable, "executor.py", "--list"])\n'
        test_script_content += "    print(tools_output)\n\n"
        test_script_content += "    # Parse tools\n"
        test_script_content += "    try:\n"
        test_script_content += "        tools = json.loads(tools_output)\n"
        test_script_content += "        if tools and len(tools) > 0:\n"
        test_script_content += '            first_tool = tools[0]["name"]\n\n'
        test_script_content += "            # Test describing a tool\n"
        test_script_content += (
            '            print(f"\\n2. Describing tool: {first_tool}")\n'
        )
        test_script_content += '            describe_output = run_command([sys.executable, "executor.py", "--describe", first_tool])\n'
        test_script_content += "            print(describe_output)\n"
        test_script_content += "        else:\n"
        test_script_content += '            print("No tools found to test")\n'
        test_script_content += "    except json.JSONDecodeError:\n"
        test_script_content += '        print("Could not parse tools list")\n\n'
        test_script_content += '    print("\\nTest complete")\n\n'
        test_script_content += 'if __name__ == "__main__":\n'
        test_script_content += "    main()\n"

        test_script_path = examples_dir / "test_skill.py"
        with open(test_script_path, "w") as f:
            f.write(test_script_content)

        test_script_path.chmod(0o755)
        print(f"✓ Added test script: {test_script_path}")


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
    print(f"  - README.md (usage documentation)")
    print(f"  - examples/test_skill.py (test script)")

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
        epilog="Example: python scripts/convert_mcp_to_skill.py --mcp-config github-mcp.json --output-dir ./skills/github",
    )
    parser.add_argument(
        "--mcp-config", required=True, help="Path to MCP server configuration JSON"
    )
    parser.add_argument(
        "--output-dir", required=True, help="Output directory for generated skill"
    )

    args = parser.parse_args()

    # Check if mcp-config exists
    if not os.path.exists(args.mcp_config):
        print(f"Error: MCP config file not found: {args.mcp_config}")
        sys.exit(1)

    asyncio.run(convert_mcp_to_skill(args.mcp_config, args.output_dir))


if __name__ == "__main__":
    main()
