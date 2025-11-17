#!/usr/bin/env python3
"""
Tests for the MCP to Skill converter.

Tests the conversion of MCP server configurations to Claude Skills.
"""

import json
import pytest
from pathlib import Path
import sys

# Add the scripts directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from convert_mcp_to_skill import MCPSkillGenerator


@pytest.mark.asyncio
async def test_convert_filesystem_mcp_to_skill(tmp_path):
    """
    Test converting the @modelcontextprotocol/server-filesystem MCP server to a skill.

    This uses one of the simplest and most commonly used public MCP servers.
    """
    # Create a simple filesystem MCP configuration
    mcp_config = {
        "name": "filesystem",
        "description": "Filesystem access via MCP",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        "env": {}
    }

    # Create output directory in tmp_path
    output_dir = tmp_path / "filesystem-skill"

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

    # Verify mcp-config.json contains the correct configuration
    with open(mcp_config_json) as f:
        saved_config = json.load(f)

    assert saved_config["name"] == "filesystem", "Config should preserve server name"
    assert saved_config["command"] == "npx", "Config should preserve command"
    assert "@modelcontextprotocol/server-filesystem" in saved_config["args"], \
        "Config should preserve MCP server package"

    # Verify SKILL.md has content
    skill_content = skill_md.read_text()
    assert len(skill_content) > 0, "SKILL.md should have content"
    assert "filesystem" in skill_content.lower(), "SKILL.md should reference the server name"

    # Verify README.md has content
    readme_content = readme_md.read_text()
    assert len(readme_content) > 0, "README.md should have content"

    # Verify executor.py is executable-ready (has proper shebang)
    executor_content = executor_py.read_text()
    assert executor_content.startswith("#!/usr/bin/env python3"), \
        "executor.py should have proper shebang"


@pytest.mark.asyncio
async def test_validate_config_missing_fields(tmp_path):
    """Test that configuration validation catches missing required fields."""
    # Missing 'command' field
    invalid_config = {
        "name": "test-server",
        "args": []
    }

    output_dir = tmp_path / "test-skill"
    generator = MCPSkillGenerator(invalid_config, output_dir)

    # Validation should raise ValueError
    with pytest.raises(ValueError, match="missing required fields"):
        generator._validate_config()


@pytest.mark.asyncio
async def test_validate_config_invalid_args_type(tmp_path):
    """Test that configuration validation catches invalid args type."""
    # 'args' should be a list, not a string
    invalid_config = {
        "name": "test-server",
        "command": "npx",
        "args": "invalid-string"
    }

    output_dir = tmp_path / "test-skill"
    generator = MCPSkillGenerator(invalid_config, output_dir)

    # Validation should raise ValueError
    with pytest.raises(ValueError, match="'args' field must be a list"):
        generator._validate_config()


@pytest.mark.asyncio
async def test_validate_config_invalid_env_type(tmp_path):
    """Test that configuration validation catches invalid env type."""
    # 'env' should be a dict, not a list
    invalid_config = {
        "name": "test-server",
        "command": "npx",
        "args": [],
        "env": ["INVALID"]
    }

    output_dir = tmp_path / "test-skill"
    generator = MCPSkillGenerator(invalid_config, output_dir)

    # Validation should raise ValueError
    with pytest.raises(ValueError, match="'env' field must be a dictionary"):
        generator._validate_config()


@pytest.mark.asyncio
async def test_cleanup_removes_temp_files(tmp_path):
    """Test that temporary files are cleaned up after generation."""
    mcp_config = {
        "name": "test-server",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        "env": {}
    }

    output_dir = tmp_path / "test-skill"
    generator = MCPSkillGenerator(mcp_config, output_dir)

    # Manually add a temp file
    temp_file = output_dir / "temp_test.json"
    output_dir.mkdir(parents=True, exist_ok=True)
    temp_file.write_text("{}")
    generator.temp_files.append(temp_file)

    # Run cleanup
    generator._cleanup()

    # Verify temp file was removed
    assert not temp_file.exists(), "Temporary files should be cleaned up"
