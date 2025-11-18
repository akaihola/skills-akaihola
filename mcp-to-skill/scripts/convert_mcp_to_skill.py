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

Note: This script requires a local mcp_to_skill.py converter script to be present
in the same directory.
"""

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


class MCPSkillGenerator:
    """Generate a Skill from an MCP server configuration."""

    def __init__(self, mcp_config: dict[str, Any], output_dir: Path):
        self.mcp_config = mcp_config
        self.output_dir = Path(output_dir)
        self.server_name = mcp_config.get("name", "unnamed-mcp-server")
        self.temp_files = []  # Track temporary files for cleanup

    def _validate_config(self):
        """Validate the MCP configuration structure."""
        required_fields = ["name", "command"]
        missing_fields = [
            field for field in required_fields if field not in self.mcp_config
        ]

        if missing_fields:
            raise ValueError(
                f"MCP config missing required fields: {', '.join(missing_fields)}"
            )

        if not isinstance(self.mcp_config.get("args", []), list):
            raise ValueError("MCP config 'args' field must be a list")

        if "env" in self.mcp_config and not isinstance(self.mcp_config["env"], dict):
            raise ValueError("MCP config 'env' field must be a dictionary")

        print("✓ MCP configuration validated")

    async def generate(self):
        """Generate the complete skill structure."""
        try:
            # Validate configuration first
            self._validate_config()

            # Check if output directory exists and has files
            if self.output_dir.exists() and any(self.output_dir.iterdir()):
                print(f"Warning: Output directory {self.output_dir} is not empty")
                print("Existing files may be overwritten")

            self.output_dir.mkdir(parents=True, exist_ok=True)

            print(f"Generating skill for MCP server: {self.server_name}")

            # 1. Run the converter to generate the skill
            await self._run_converter()

            # 2. Add additional documentation
            self._add_documentation()

            # 3. Add example usage
            self._add_examples()

            print(f"✓ Skill generated at: {self.output_dir}")
        finally:
            # Clean up temporary files
            self._cleanup()

    def _check_local_converter(self):
        """Check if the local converter script exists."""
        local_converter = Path(__file__).parent / "mcp_to_skill.py"

        if not local_converter.exists():
            print("Error: Local converter script not found!")
            print(f"Expected at: {local_converter}")
            sys.exit(1)

        print("Using local converter script...")

    async def _run_converter(self):
        """Run the local converter script."""
        print("Running converter script...")

        # Check if local converter exists
        self._check_local_converter()

        # Create a temporary config file
        temp_config_path = self.output_dir / "temp_mcp_config.json"
        self.temp_files.append(temp_config_path)  # Track for cleanup

        with open(temp_config_path, "w") as f:
            json.dump(self.mcp_config, f, indent=2)

        # Run the converter directly from the scripts directory
        try:
            cmd = [
                sys.executable,
                str(Path(__file__).parent / "mcp_to_skill.py"),
                "--mcp-config",
                str(temp_config_path),
                "--output-dir",
                str(self.output_dir),
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            print(result.stdout)

        except subprocess.CalledProcessError as e:
            print(f"Error running local converter: {e}")
            print(f"Stdout: {e.stdout}")
            print(f"Stderr: {e.stderr}")
            sys.exit(1)

    def _add_documentation(self):
        """Add additional documentation to the generated skill."""
        docs_dir = self.output_dir / "docs"
        docs_dir.mkdir(exist_ok=True)

        # Load README template
        template_path = (
            Path(__file__).parent.parent / "assets" / "templates" / "README.md.template"
        )
        try:
            with open(template_path, "r") as f:
                readme_template = f.read()
        except FileNotFoundError:
            print(f"Error: Template file not found: {template_path}")
            print("Skipping README generation")
            return
        except IOError as e:
            print(f"Error reading template file: {e}")
            print("Skipping README generation")
            return

        # Populate template
        estimated_tokens = len(self.mcp_config.get("tools", [])) * 500
        readme_content = readme_template.format(
            server_name=self.server_name, estimated_tokens=estimated_tokens
        )

        readme_path = self.output_dir / "README.md"
        with open(readme_path, "w") as f:
            f.write(readme_content)

        print(f"✓ Added documentation: {readme_path}")

    def _add_examples(self):
        """Add example usage files."""
        examples_dir = self.output_dir / "examples"
        examples_dir.mkdir(exist_ok=True)

        # Load test script template
        template_path = (
            Path(__file__).parent.parent
            / "assets"
            / "templates"
            / "test_skill.py.template"
        )
        try:
            with open(template_path, "r") as f:
                test_script_content = f.read()
        except FileNotFoundError:
            print(f"Error: Template file not found: {template_path}")
            print("Skipping test script generation")
            return
        except IOError as e:
            print(f"Error reading template file: {e}")
            print("Skipping test script generation")
            return

        test_script_path = examples_dir / "test_skill.py"
        with open(test_script_path, "w") as f:
            f.write(test_script_content)

        test_script_path.chmod(0o755)
        print(f"✓ Added test script: {test_script_path}")

    def _cleanup(self):
        """Clean up temporary files."""
        for temp_file in self.temp_files:
            try:
                if temp_file.exists():
                    temp_file.unlink()
                    print(f"✓ Cleaned up: {temp_file.name}")
            except Exception as e:
                print(f"Warning: Could not delete temporary file {temp_file}: {e}")


async def convert_mcp_to_skill(mcp_config_path: str, output_dir: str) -> None:
    """Convert an MCP server configuration to a Skill."""

    # Load MCP config
    try:
        with open(mcp_config_path) as f:
            mcp_config = json.load(f)
    except FileNotFoundError:
        print(f"Error: MCP config file not found: {mcp_config_path}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in config file: {e}")
        sys.exit(1)
    except IOError as e:
        print(f"Error reading config file: {e}")
        sys.exit(1)

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
    print(f"   uv pip install mcp")
    print(f"\n2. Copy to Claude skills directory:")
    print(f"   cp -r {output_dir} ~/.claude/skills/")
    print(f"\n3. Claude will discover it automatically")

    print(f"\nContext savings:")
    print(f"  Before (MCP): All tools preloaded (~10k-50k tokens)")
    print(f"  After (Skill): ~100 tokens until used")
    print(f"  Reduction: ~90-99%")


def main() -> None:
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
