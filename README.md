# skills-akaihola

[![Built with Claude Code](https://img.shields.io/badge/Built_with-Claude_Code-6f42c1?logo=anthropic&logoColor=white)](https://claude.ai/code)

> This project is developed by an AI coding agent ([Claude Code](https://claude.ai/code)), with human oversight and direction.

A collection of [Claude Code skills](https://docs.claude.com/en/docs/claude-code/skills)
for personal use. Each skill is a self-contained folder with a `SKILL.md` and
supporting scripts.

## Skills

| Skill | Description |
|-------|-------------|
| `brave-search` | Web search via Brave Search API |
| `clasohlson` | Clas Ohlson product search |
| `context7-skill` | Context7 integration |
| `conventional-committer` | Conventional commit message generation |
| `credentials-check` | Credential leak detection |
| `email-mailbox-analyzer` | Email mailbox analysis |
| `himalaya-email-manager` | Email management via Himalaya CLI |
| `hsl` | Helsinki region public transport routes and departures via Digitransit |
| `markdown-pm` | Obsidian-style project management |
| `mcp-to-skill` | Convert MCP servers to skills |
| `motonet` | Motonet product search |
| `nano-banana-image` | Image generation via nano-banana |
| `notebooklm` | NotebookLM integration |
| `power` | Power management utilities |
| `tokmanni` | Tokmanni product search |
| `verkkokauppa` | Verkkokauppa.com product search |
| `youtube-frame-analysis` | Extract scene-change frames from YouTube videos and analyse visuals with Gemini |
| `youtube-to-markdown` | YouTube video to Markdown conversion |
| `youtube-transcription` | YouTube transcript extraction |
| `zed-threads` | Zed editor thread management |

## Installation

Clone and symlink individual skills into your `.claude/skills/` directory:

```bash
git clone https://github.com/akaihola/skills-akaihola.git
ln -s /path/to/skills-akaihola/markdown-pm ~/.claude/skills/markdown-pm
```

## License

For personal use.
