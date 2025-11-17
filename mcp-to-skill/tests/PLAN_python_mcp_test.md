# Test Plan: Python-Based MCP Server Conversion

## Objective
Create a pytest test for converting the simplest commonly used and publicly available Python-based MCP server to a skill using the mcp-to-skill converter.

## Selected MCP Server

**Server**: Weather MCP Server (FastMCP-based)
- **Package**: `mcp` (official Model Context Protocol SDK)
- **Installation**: `uv pip install "mcp[cli]"`
- **Why this server?**
  - Official tutorial example from modelcontextprotocol.io
  - Simple, focused functionality (weather lookup)
  - Commonly used in MCP documentation and tutorials
  - Uses FastMCP (modern, Pythonic approach)
  - Minimal dependencies (mcp, httpx)
  - Python 3.10+ compatible

## Server Configuration Structure

```json
{
  "name": "weather",
  "description": "Get current weather information",
  "command": "uv",
  "args": ["--directory", "/path/to/weather", "run", "weather.py"],
  "env": {}
}
```

## Test Server Implementation

The test will create a minimal weather server inline:

```python
# weather.py - Minimal test server
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("weather")

@mcp.tool()
def get_weather(city: str) -> str:
    """Get current weather for a city"""
    # Mock implementation for testing
    return f"Weather in {city}: 72°F, Sunny"

@mcp.resource("weather://{city}")
def weather_resource(city: str) -> str:
    """Get weather as a resource"""
    return f"Weather data for {city}"
```

## Test Structure

### Test File Location
`mcp-to-skill/tests/test_convert_python_mcp_to_skill.py`

### Test Cases

#### 1. `test_convert_weather_mcp_to_skill` (Primary Integration Test)
- **Purpose**: End-to-end test converting a Python weather MCP server to a skill
- **Setup**:
  - Create `tmp_path` temporary directory
  - Write minimal weather.py server file
  - Create MCP configuration JSON
- **Actions**:
  - Run MCPSkillGenerator.generate()
- **Assertions**:
  - Verify output directory structure:
    - `SKILL.md` exists and contains server name
    - `executor.py` exists with proper shebang
    - `mcp-config.json` exists with correct configuration
    - `README.md` exists with content
    - `examples/test_skill.py` exists
  - Verify mcp-config.json preserves:
    - `command: "uv"`
    - `args` includes "run" and "weather.py"
    - `name: "weather"`
  - Verify executor.py can communicate with Python MCP server

#### 2. `test_python_uv_command_structure`
- **Purpose**: Ensure Python MCP servers using `uv` command are handled correctly
- **Setup**: Create config with `uv` command and proper args structure
- **Actions**: Validate configuration
- **Assertions**: Confirm `uv` command and args are preserved

#### 3. `test_python_mcp_with_directory_arg`
- **Purpose**: Test handling of `--directory` argument common in Python MCP configs
- **Setup**: Config with `--directory` in args
- **Actions**: Generate skill
- **Assertions**: Verify `--directory` path is maintained in generated config

#### 4. `test_python_vs_nodejs_detection` (Optional)
- **Purpose**: Document behavior differences between Python and Node.js MCP servers
- **Setup**: Create both Python and Node.js configs
- **Actions**: Generate both skills
- **Assertions**: 
  - Python uses `uv` command
  - Node.js uses `npx` command
  - Both generate valid skills

## Dependencies Required

### For Test Execution
- `pytest` - Test framework (already installed)
- `pytest-asyncio` - Async test support (already installed)

### For Runtime Testing (Optional - if testing actual MCP communication)
- `mcp[cli]` - MCP SDK with CLI tools
- `httpx` - HTTP client (weather server dependency)

## Key Differences: Python vs Node.js MCP Servers

| Aspect | Node.js MCP | Python MCP |
|--------|-------------|------------|
| **Command** | `npx` | `uv` |
| **Package Install** | `npx -y @package/name` | `uv --directory /path run script.py` |
| **Args Structure** | `["-y", "@package/name", ...params]` | `["--directory", "/path", "run", "script.py"]` |
| **Config Pattern** | Package-based execution | Script-based execution |

## Success Criteria

1. Test successfully converts Python weather MCP server to skill
2. Generated skill structure matches expected format
3. MCP configuration properly preserves `uv` command structure
4. All files are created in `tmp_path` temporary directory
5. No external network calls during test (mock weather data)
6. Test runs in under 5 seconds
7. All assertions pass

## Implementation Steps

1. ✅ Research Python MCP servers
2. ✅ Identify simplest commonly used server (weather)
3. ✅ Analyze requirements and structure
4. ✅ Design test structure and test cases
5. ⏳ Write pytest test implementation
6. ⏳ Verify test runs successfully
7. ⏳ Document any edge cases or limitations

## Edge Cases to Consider

1. **Path Resolution**: Python MCP servers often use `--directory` for path specification
2. **Virtual Environments**: `uv` manages its own venv, ensure this doesn't interfere
3. **Script vs Package**: Python servers are often script-based, not npm packages
4. **Dependencies**: Weather server needs `httpx`, test should handle missing deps gracefully
5. **Python Version**: Ensure Python 3.10+ compatibility check

## Notes

- The converter already handles Node.js MCP servers well (filesystem test proves this)
- Python MCP servers have a different invocation pattern that needs validation
- The weather server is the canonical example from official MCP docs (2025)
- Using FastMCP makes the server code very concise and testable
