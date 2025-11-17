# Converter Technical Details

## Conversion Process

The MCP to Skill converter transforms MCP server configurations into Claude Skills through a multi-step process.

### Step 1: Configuration Validation

Load and validate the MCP server configuration:

```json
{
  "name": "server-name",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-name"],
  "env": {"ENV_VAR": "value"}
}
```

### Step 2: Tool Discovery
The converter connects to the MCP server to:
- Discover available tools
- Extract tool schemas
- Generate tool descriptions

### Step 3: Skill Generation
The converter creates:
- A SKILL.md with instructions for Claude
- An executor.py script for dynamic tool invocation
- Configuration files for the generated skill

### Step 4: Documentation Enhancement
Additional documentation is added:
- README.md with usage instructions
- Test scripts for validation
- Examples for common use cases

## Implementation Details

### Executor Script

The executor.py script handles dynamic communication with the MCP server:

```python
class MCPExecutor:
    async def connect(self):
        """Connect to MCP server."""
        # Establish connection using stdio_client
        
    async def list_tools(self):
        """Get list of available tools."""
        # Query MCP server for tools
        
    async def describe_tool(self, tool_name: str):
        """Get detailed schema for a specific tool."""
        # Retrieve tool schema
        
    async def call_tool(self, tool_name: str, arguments: dict):
        """Execute a tool call."""
        # Invoke tool with arguments
```

### Progressive Disclosure Implementation

1. **Metadata Loading**
   - Only skill name and description loaded initially
   - Claude can decide when to use the skill
   - Minimal context impact

2. **Full Instructions Loading**
   - Complete tool list and descriptions loaded when needed
   - Claude can select appropriate tools
   - Moderate context usage

3. **Dynamic Execution**
   - Tools executed through external process
   - No tool definitions loaded into context
   - Maximum context efficiency

## Context Optimization

For detailed context optimization strategies, token usage comparisons, and performance considerations, see `context_optimization.md`.

## Compatibility

### Supported MCP Servers
The converter works with any standard MCP server:
- @modelcontextprotocol/server-github
- @modelcontextprotocol/server-slack
- @modelcontextprotocol/server-filesystem
- @modelcontextprotocol/server-postgres
- Custom MCP servers

### Requirements
- Python 3.8+
- mcp package (install with `uv pip install mcp`)
- Internet connection (for downloading converter)

## Limitations

### Current Limitations
- Early stage implementation
- Some complex authentication may need adjustments
- Not all MCP servers tested
- Requires Python environment

### Known Issues
- OAuth flows may need manual configuration
- Some server-specific features might not be fully supported
- Error handling could be improved

## Future Enhancements

### Planned Improvements
- Support for more authentication methods
- Better error handling and recovery
- Performance optimizations
- Additional MCP server testing

### Potential Extensions
- Batch conversion of multiple MCP servers
- Automatic skill installation
- Integration with skill management tools
- Visual configuration interface

## Troubleshooting

### Common Issues

1. **Converter Download Fails**
   - Check internet connection
   - Verify GitHub accessibility
   - Try manual download

2. **MCP Server Connection Fails**
   - Verify server configuration
   - Check environment variables
   - Ensure server is accessible

3. **Generated Skill Doesn't Work**
   - Install mcp package: `uv pip install mcp`
   - Check executor permissions
   - Verify MCP server is running

### Debugging Steps

1. Test MCP server independently
2. Verify configuration file format
3. Check converter script output
4. Test generated skill manually
5. Review error messages

## Resources

- [MCP to Skill Converter Repository](https://github.com/GBSOSS/-mcp-to-skill-converter)
- [MCP Specification](https://modelcontextprotocol.io/)
- [Claude Skills Documentation](https://docs.anthropic.com/claude/docs/skills)
- [Progressive Disclosure Pattern](https://github.com/lackeyjb/playwright-skill)