# MCP to Skill Converter

Convert Model Context Protocol (MCP) servers into Claude Skills with 90-99% context savings using progressive disclosure.

## What This Does

Transforms MCP servers into Claude Skills that load tools on-demand instead of preloading all tool definitions. This dramatically reduces context token usage while maintaining full functionality.

## Installation

```bash
# 1. Convert an MCP server config to a skill
python scripts/convert_mcp_to_skill.py \
  --mcp-config path/to/config.json \
  --output-dir ./output-dir

# 2. Install dependencies in the generated skill
cd ./output-dir
uv pip install mcp

# 3. Install the skill for Claude
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

## When to Use This

**Convert to skill** if you have 10+ tools and want to maximize available context.

**Keep using MCP directly** if you have 5 or fewer tools, need OAuth flows, or require persistent connections.

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
- mcp package (install with `uv pip install mcp`)
- Internet connection (for downloading converter)

## Testing Generated Skills

```bash
cd skill-directory

# List tools
python executor.py --list

# Describe a tool
python executor.py --describe tool_name

# Call a tool
python executor.py --call '{"tool": "tool_name", "arguments": {...}}'
```

## Troubleshooting

**"mcp package not found"**: Run `uv pip install mcp`

**"MCP server not responding"**: Verify command, arguments, and environment variables in your config file

## Credits

This skill uses the mcp-to-skill-converter from https://github.com/GBSOSS/-mcp-to-skill-converter

Inspired by:
- playwright-skill by @lackeyjb
- Anthropic Skills framework
- Model Context Protocol