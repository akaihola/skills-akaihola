# MCP Basics

## Model Context Protocol Overview

The Model Context Protocol (MCP) is a standardized protocol for connecting AI models to external tools and data sources. MCP servers expose tools that AI assistants can discover and invoke dynamically.

## MCP Server Configuration

MCP servers are configured using JSON files that specify how to launch and communicate with the server.

### Basic Configuration Format

```json
{
  "name": "server-name",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-name"],
  "env": {
    "API_KEY": "your-api-key",
    "OTHER_VAR": "value"
  }
}
```

### Configuration Fields

- `name`: Human-readable identifier for the server
- `command`: Command to start the server process
- `args`: Arguments passed to the command
- `env`: Environment variables for the server process

## Common MCP Servers

### GitHub MCP Server
```json
{
  "name": "github",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-github"],
  "env": {
    "GITHUB_TOKEN": "your-github-token"
  }
}
```

### Slack MCP Server
```json
{
  "name": "slack",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-slack"],
  "env": {
    "SLACK_BOT_TOKEN": "your-slack-bot-token"
  }
}
```

### Filesystem MCP Server
```json
{
  "name": "filesystem",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/directory"],
  "env": {}
}
```

## Context Considerations

For detailed information about context optimization strategies and when to use MCP vs Skills, see `context_optimization.md`.

## Best Practices

1. **Environment Variables**: Store sensitive data in environment variables, not in config files
2. **Tool Naming**: Use descriptive tool names that clearly indicate functionality
3. **Documentation**: Provide clear descriptions for tools and parameters
4. **Error Handling**: Implement robust error handling in MCP servers
5. **Testing**: Test MCP servers thoroughly before converting to skills

## Troubleshooting

### Common Issues

1. **Server Not Starting**
   - Check command and arguments
   - Verify environment variables
   - Ensure dependencies are installed

2. **Tools Not Discovered**
   - Check server initialization
   - Verify protocol implementation
   - Check for authentication issues

3. **Tool Execution Failures**
   - Verify input parameters match schema
   - Check for permission issues
   - Review server logs for errors

### Debugging Tips

1. Use verbose logging to trace protocol exchanges
2. Test with simple tools first
3. Check network connectivity for remote servers
4. Verify environment variable values

## Resources

- [MCP Specification](https://modelcontextprotocol.io/)
- [MCP GitHub Repository](https://github.com/modelcontextprotocol/)
- [MCP Server Examples](https://github.com/modelcontextprotocol/servers)