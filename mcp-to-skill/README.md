# MCP to Skill Converter

This skill converts any MCP (Model Context Protocol) server into a Claude Skill using the progressive disclosure pattern, resulting in significant context savings and improved performance.

## Overview

The MCP to Skill Converter applies the "progressive disclosure" pattern to MCP servers:
- **At startup**: Only skill metadata is loaded (~100 tokens)
- **On use**: Full tool list and instructions are loaded (~5k tokens)
- **On execution**: Tools are called dynamically (0 context tokens)

This approach can reduce context usage by 90-99% compared to traditional MCP implementations.

## Benefits

### Context Efficiency
- Traditional MCP: All tools loaded at startup (10-50k tokens for 20+ tools)
- Skill approach: Metadata only (~100 tokens) until used
- Result: More context available for actual work

### Performance
- Faster startup with minimal context loading
- Efficient tool execution without context overhead
- Better memory usage for large tool sets

## Quick Start

1. Create an MCP configuration file (see examples in `assets/examples/`)
2. Run the converter:
   ```bash
   python scripts/convert_mcp_to_skill.py --mcp-config path/to/config.json --output-dir ./output-dir
   ```
3. Install dependencies:
   ```bash
   cd ./output-dir
   pip install mcp
   ```
4. Install the skill:
   ```bash
   cp -r ./output-dir ~/.claude/skills/skill-name
   ```

## Examples

### GitHub MCP Server

```bash
# Create config
cat > github.json << 'EOF'
{
  "name": "github",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-github"],
  "env": {"GITHUB_TOKEN": "your-github-token"}
}
EOF

# Convert to skill
python scripts/convert_mcp_to_skill.py --mcp-config github.json --output-dir ./skills/github
```

### Multiple MCP Servers

```bash
# Convert multiple MCP servers
for config in assets/examples/*.json; do
  name=$(basename "$config" .json)
  python scripts/convert_mcp_to_skill.py --mcp-config "$config" --output-dir "./skills/$name"
done
```

## When to Use

### Use this converter when:
- You have 10+ MCP tools
- Context space is tight
- Most tools won't be used in each conversation
- Tools are independent

### Stick with MCP when:
- You have 1-5 tools
- Need complex OAuth flows
- Need persistent connections
- Cross-platform compatibility is critical

## Structure

```
mcp-to-skill/
├── SKILL.md                    # Main instructions for Claude
├── README.md                   # This file
├── scripts/
│   └── convert_mcp_to_skill.py # Main converter script
├── references/
│   ├── mcp_basics.md           # MCP protocol fundamentals
│   ├── converter_details.md    # Technical converter details
│   └── context_optimization.md # Context optimization strategies
└── assets/examples/
    ├── github-mcp.json         # GitHub MCP configuration
    ├── slack-mcp.json          # Slack MCP configuration
    ├── filesystem-mcp.json     # Filesystem MCP configuration
    └── postgres-mcp.json       # Postgres MCP configuration
```

## Requirements

- Python 3.8+
- mcp package (install with `pip install mcp`)
- Internet connection (for downloading converter)

## Troubleshooting

### "mcp package not found"
```bash
pip install mcp
```

### "MCP server not responding"
Check your config file:
- Command is correct
- Environment variables are set
- Server is accessible

### Testing generated skills
```bash
cd skill-directory

# List tools
python executor.py --list

# Describe a tool
python executor.py --describe tool_name

# Call a tool
python executor.py --call '{"tool": "tool_name", "arguments": {...}}'
```

## Performance Comparison

Real example with GitHub MCP server (8 tools):

| Metric | MCP | Skill | Savings |
|--------|-----|-------|---------|
| Idle | 8,000 tokens | 100 tokens | 98.75% |
| Active | 8,000 tokens | 5,000 tokens | 37.5% |

## Credits

This skill uses the mcp-to-skill-converter from https://github.com/GBSOSS/-mcp-to-skill-converter

Inspired by:
- playwright-skill by @lackeyjb
- Anthropic Skills framework
- Model Context Protocol