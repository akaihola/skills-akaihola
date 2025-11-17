#!/usr/bin/env python3
"""
Tests for converting Python-based MCP servers to skills.

Tests the conversion of Python MCP server configurations (using uv command)
to Claude Skills. These servers use a different invocation pattern than
Node.js MCP servers (npx command).
"""

import json
import pytest
from pathlib import Path
import sys

# Add the scripts directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from convert_mcp_to_skill import MCPSkillGenerator


@pytest.mark.asyncio
async def test_convert_weather_mcp_to_skill(tmp_path):
    """
    Test converting a Python weather MCP server to a skill.

    This is an integration test that converts the simplest commonly used
    Python-based MCP server (weather using FastMCP) to a skill.
    """
    # Create a minimal weather server file in tmp_path
    server_dir = tmp_path / "weather_server"
    server_dir.mkdir()

    weather_py = server_dir / "weather.py"
    weather_py.write_text(
        '''#!/usr/bin/env python3
"""Minimal weather MCP server for testing."""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("weather")

@mcp.tool()
def get_weather(city: str) -> str:
    """Get current weather for a city."""
    # Mock implementation for testing
    return f"Weather in {city}: 72°F, Sunny"

@mcp.resource("weather://{city}")
def weather_resource(city: str) -> str:
    """Get weather as a resource."""
    return f"Weather data for {city}"

if __name__ == "__main__":
    mcp.run()
'''
    )

    # Create MCP configuration for Python weather server
    mcp_config = {
        "name": "weather",
        "description": "Get current weather information",
        "command": "uv",
        "args": ["--directory", str(server_dir), "run", "weather.py"],
        "env": {},
    }

    # Create output directory in tmp_path
    output_dir = tmp_path / "weather-skill"

    # Generate the skill
    generator = MCPSkillGenerator(mcp_config, output_dir)
    await generator.generate()

    # Verify the expected files were created
    assert output_dir.exists(), "Output directory should exist"

    # Check for core files
    skill_md = output_dir / "SKILL.md"
    assert skill_md.exists(), "SKILL.md should be created"

    executor_py = output_dir / "executor.py"
    assert executor_py.exists(), "executor.py should be created"

    mcp_config_json = output_dir / "mcp-config.json"
    assert mcp_config_json.exists(), "mcp-config.json should be created"

    readme_md = output_dir / "README.md"
    assert readme_md.exists(), "README.md should be created"

    # Check examples directory
    examples_dir = output_dir / "examples"
    assert examples_dir.exists(), "examples directory should exist"

    test_script = examples_dir / "test_skill.py"
    assert test_script.exists(), "test_skill.py should be created in examples"

    # Verify mcp-config.json preserves Python command structure
    with open(mcp_config_json) as f:
        saved_config = json.load(f)

    assert saved_config["name"] == "weather", "Config should preserve server name"
    assert saved_config["command"] == "uv", "Config should preserve 'uv' command"
    assert (
        "run" in saved_config["args"]
    ), "Config args should include 'run' for Python execution"
    assert (
        "weather.py" in saved_config["args"]
    ), "Config args should include script name"
    assert (
        "--directory" in saved_config["args"]
    ), "Config args should include --directory flag"

    # Verify SKILL.md has content and references the server
    skill_content = skill_md.read_text()
    assert len(skill_content) > 0, "SKILL.md should have content"
    assert (
        "weather" in skill_content.lower()
    ), "SKILL.md should reference the server name"

    # Verify README.md has content
    readme_content = readme_md.read_text()
    assert len(readme_content) > 0, "README.md should have content"

    # Verify executor.py is executable-ready (has proper shebang)
    executor_content = executor_py.read_text()
    assert executor_content.startswith(
        "#!/usr/bin/env python3"
    ), "executor.py should have proper shebang"


@pytest.mark.asyncio
async def test_python_uv_command_structure(tmp_path):
    """
    Test that Python MCP servers using `uv` command are handled correctly.

    This validates that the converter properly preserves the uv command structure,
    which is different from Node.js npx-based servers.
    """
    # Create a simple MCP configuration with uv command
    mcp_config = {
        "name": "python-mcp-server",
        "description": "A Python-based MCP server",
        "command": "uv",
        "args": ["--directory", "/path/to/server", "run", "server.py"],
        "env": {},
    }

    output_dir = tmp_path / "python-mcp-skill"
    generator = MCPSkillGenerator(mcp_config, output_dir)

    # Validation should pass
    generator._validate_config()

    # Verify command structure is preserved
    assert generator.mcp_config["command"] == "uv", "Command should be 'uv'"
    assert isinstance(generator.mcp_config["args"], list), "Args should be a list"
    assert len(generator.mcp_config["args"]) > 0, "Args should not be empty"


@pytest.mark.asyncio
async def test_python_mcp_with_directory_arg(tmp_path):
    """
    Test handling of `--directory` argument common in Python MCP configs.

    Python MCP servers often use --directory to specify the working directory
    for the script. This test ensures the converter maintains this structure.
    """
    server_dir = tmp_path / "my_server"
    server_dir.mkdir()

    # Create MCP config with --directory argument
    mcp_config = {
        "name": "custom-python-server",
        "description": "Custom Python MCP server",
        "command": "uv",
        "args": ["--directory", str(server_dir), "run", "main.py", "--port", "3000"],
        "env": {"DEBUG": "true"},
    }

    output_dir = tmp_path / "custom-skill"
    generator = MCPSkillGenerator(mcp_config, output_dir)
    await generator.generate()

    # Verify mcp-config.json maintains --directory path
    with open(output_dir / "mcp-config.json") as f:
        saved_config = json.load(f)

    assert (
        "--directory" in saved_config["args"]
    ), "Config should preserve --directory flag"
    # The directory path should be preserved in the saved config
    args = saved_config["args"]
    dir_index = args.index("--directory")
    assert dir_index + 1 < len(args), "Directory path should follow --directory flag"
    assert str(server_dir) in saved_config["args"] or saved_config["args"][
        dir_index + 1
    ] == str(server_dir), "Config should preserve server directory path"

    # Verify other command arguments are preserved
    assert "main.py" in saved_config["args"], "Config should preserve script name"
    assert (
        "--port" in saved_config["args"]
    ), "Config should preserve additional arguments"
    assert "3000" in saved_config["args"], "Config should preserve argument values"

    # Verify environment variables are preserved
    assert (
        "DEBUG" in saved_config["env"]
    ), "Config should preserve environment variables"
    assert (
        saved_config["env"]["DEBUG"] == "true"
    ), "Config should preserve environment variable values"


@pytest.mark.asyncio
async def test_python_vs_nodejs_detection(tmp_path):
    """
    Test that the converter handles both Python and Node.js MCP servers correctly.

    This documents the behavior differences between Python (uv) and Node.js (npx)
    MCP server configurations.
    """
    # Create Python MCP config
    python_config = {
        "name": "python-server",
        "description": "Python MCP server",
        "command": "uv",
        "args": ["--directory", "/path/to/python", "run", "server.py"],
        "env": {},
    }

    # Create Node.js MCP config
    nodejs_config = {
        "name": "nodejs-server",
        "description": "Node.js MCP server",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        "env": {},
    }

    python_output_dir = tmp_path / "python-skill"
    nodejs_output_dir = tmp_path / "nodejs-skill"

    # Generate both skills
    python_generator = MCPSkillGenerator(python_config, python_output_dir)
    nodejs_generator = MCPSkillGenerator(nodejs_config, nodejs_output_dir)

    await python_generator.generate()
    await nodejs_generator.generate()

    # Load both generated configs
    with open(python_output_dir / "mcp-config.json") as f:
        python_saved_config = json.load(f)

    with open(nodejs_output_dir / "mcp-config.json") as f:
        nodejs_saved_config = json.load(f)

    # Verify Python config uses uv command
    assert (
        python_saved_config["command"] == "uv"
    ), "Python server should use 'uv' command"
    assert (
        "--directory" in python_saved_config["args"]
    ), "Python server should use --directory"
    assert (
        "run" in python_saved_config["args"]
    ), "Python server should use 'run' subcommand"

    # Verify Node.js config uses npx command
    assert (
        nodejs_saved_config["command"] == "npx"
    ), "Node.js server should use 'npx' command"
    assert "-y" in nodejs_saved_config["args"], "Node.js server should use -y flag"
    assert (
        "@modelcontextprotocol/server-filesystem" in nodejs_saved_config["args"]
    ), "Node.js server should use package reference"

    # Verify both directories exist (generation succeeded for both)
    assert python_output_dir.exists(), "Python skill output directory should exist"
    assert nodejs_output_dir.exists(), "Node.js skill output directory should exist"

    # Verify both have the required files
    for skill_dir in [python_output_dir, nodejs_output_dir]:
        assert (
            skill_dir / "SKILL.md"
        ).exists(), f"SKILL.md should exist in {skill_dir}"
        assert (
            skill_dir / "executor.py"
        ).exists(), f"executor.py should exist in {skill_dir}"
        assert (
            skill_dir / "mcp-config.json"
        ).exists(), f"mcp-config.json should exist in {skill_dir}"
        assert (
            skill_dir / "README.md"
        ).exists(), f"README.md should exist in {skill_dir}"


@pytest.mark.asyncio
async def test_validate_config_missing_fields_python(tmp_path):
    """Test that Python MCP config validation catches missing required fields."""
    # Missing 'command' field
    invalid_config = {
        "name": "test-python-server",
        "args": ["--directory", "/tmp", "run", "server.py"],
    }

    output_dir = tmp_path / "test-skill"
    generator = MCPSkillGenerator(invalid_config, output_dir)

    # Validation should raise ValueError
    with pytest.raises(ValueError, match="missing required fields"):
        generator._validate_config()


@pytest.mark.asyncio
async def test_validate_config_invalid_args_type_python(tmp_path):
    """Test that Python MCP config validation catches invalid args type."""
    # 'args' should be a list, not a string
    invalid_config = {
        "name": "test-python-server",
        "command": "uv",
        "args": "--directory /tmp run server.py",  # String instead of list
    }

    output_dir = tmp_path / "test-skill"
    generator = MCPSkillGenerator(invalid_config, output_dir)

    # Validation should raise ValueError
    with pytest.raises(ValueError, match="'args' field must be a list"):
        generator._validate_config()
