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

### Traditional MCP Usage

- All tool definitions loaded at startup
- 10-50k tokens for 20+ tools
- Reduces available context for actual work
- Inefficient when only a few tools are used

### Progressive Disclosure Pattern

- Load only metadata initially (~100 tokens)
- Load full definitions when needed (~5k tokens)
- Execute tools without loading definitions (0 tokens)
- Dramatically reduces context usage

## MCP vs Skills

| Aspect | MCP | Skills |
|--------|-----|-------|
| Tool Loading | All at startup | On demand |
| Context Usage | High (10-50k tokens) | Low (100-5k tokens) |
| Performance | Consistent | Variable (better for idle) |
| Complexity | Lower | Higher (requires wrapper) |
| Best For | 1-5 tools | 10+ tools |

## When to Use Each Approach

### Use MCP Directly When:
- You have 1-5 tools
- Need complex authentication flows
- Require persistent connections
- Cross-platform compatibility is critical
- Tools are frequently used together

### Use Skills (MCP-to-Skill) When:
- You have 10+ tools
- Context space is tight
- Most tools won't be used in each conversation
- Tools are independent
- You want to maximize context for actual work

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