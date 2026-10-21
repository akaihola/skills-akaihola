# skills-akaihola

[![Built with Claude Code][built-badge]][Claude Code]

> This project is developed by an AI coding agent ([Claude Code]), with human oversight and direction.

A collection of [Claude Code skills]
for personal use. Each skill is a self-contained folder with instructions and optional scripts
or references. Some skills are agent workflows or design references.

## Tasks

[TASKS.md] holds reviewed work for the T3 pacer, with detailed
requirements in [docs/tasks/]. Read the tracker rules before
changing issue state. The older root and library backlog files retain their
existing planning records.

Machine-specific pacer configuration belongs outside this public repository.
With the pacer and Hai installed, check the configured queue without launching
work:

```bash
kandev-pacer --config ~/.config/kandev-pacer/config-t3.toml --dump-order
```

Scheduling requires a clean `main` checkout and a tracker registered against
the matching T3 project. Commit or otherwise resolve outstanding work before
running the scheduler.

## Selected skills

This table is a selection; the [library catalog] also includes local-only sources.

| Skill | Description |
|-------|-------------|
| [android-diagnostics] | Diagnose Android battery drain and slowness over adb with read-only collection and deterministic analyzers |
| [brave-search] | Web search via Brave Search API |
| [clasohlson] | Clas Ohlson product search |
| [commit] | Stage and commit logical changes with conventional commit messages |
| [commit-organizer] | Organize a messy working tree into cohesive commits, ordered by mtime |
| [context7-skill] | Context7 integration |
| [conventional-committer] | Conventional commit message generation |
| [ecb-rates] | Export historical USD/EUR rates to CSV |
| [email-mailbox-analyzer] | Email mailbox analysis |
| [himalaya-email-manager] | Email management via Himalaya CLI |
| [hsl] | Helsinki region public transport routes and departures via Digitransit |
| [learn] | Extract actionable learnings from a conversation and persist them |
| [library] | Manage the skill catalog through agent-run cookbooks |
| [mcp-to-skill] | Convert MCP servers to skills |
| [motonet] | Motonet product search |
| [nano-banana-image] | Image generation via nano-banana |
| [power] | Power webshop product search |
| [processing-scanned-receipts] | Extract and OCR scanned receipt PDFs, with cached rename previews |
| [read-as-markdown] | Read PDF, DOCX and EPUB files through a local Markdown cache |
| [rebase-all] | Rebase every branch onto main/master, keeping stacks and rewriting doc hash references |
| [secrets-scan] | Scan for credentials and report locations without values |
| [simplify-skill] | Propose which instructions in a skill, AGENTS.md or CLAUDE.md can be removed or shortened |
| [t3-start-thread] | Route child tasks, explicitly requested new conversations, and existing-thread coordination |
| [tokmanni] | Tokmanni product search |
| [verkkokauppa] | Verkkokauppa.com product search |
| [youtube-frame-analysis] | Extract scene-change frames from YouTube videos and analyse visuals with Gemini |
| [youtube-to-markdown] | YouTube video to Markdown conversion |
| [youtube-transcription] | YouTube transcript extraction |
| [zed-threads] | Zed editor thread management |

## Plugins

This repo also doubles as a Claude Code plugin marketplace
(see [.claude-plugin/marketplace.json]).

| Plugin | Description |
|--------|-------------|
| `reflect-extensions` | Session retrospective: extracts learnings and maps them onto the right extension surface (skills, MCP, commands, subagents, hooks, plugins); ships a `/reflect-extensions` command and an end-of-session reminder hook. |

Install a plugin with:

```bash
claude plugin marketplace add akaihola/skills-akaihola
claude plugin install reflect-extensions@skills-akaihola
```

## Installation

Clone and symlink individual skills into the agent’s discovery directory.
Create the destination first:

```bash
git clone https://github.com/akaihola/skills-akaihola.git
mkdir -p ~/.claude/skills
ln -s /path/to/skills-akaihola/tokmanni ~/.claude/skills/tokmanni
```

## Metadata validation

Run the offline check for every Git-tracked `SKILL.md` before publishing changes:

```bash
uv run --no-project --with pyyaml python scripts/check_skill_metadata.py
uv run --no-project --with pyyaml --with pytest pytest tests/test_skill_metadata.py -q
```

The check requires YAML frontmatter with nonempty string names and descriptions.
Failures identify the skill path. CI runs it for skill metadata changes.

## License

For personal use.

[TASKS.md]: TASKS.md
[docs/tasks/]: docs/tasks/
[library catalog]: library/library.yaml
[.claude-plugin/marketplace.json]: .claude-plugin/marketplace.json
[android-diagnostics]: android-diagnostics/SKILL.md
[brave-search]: brave-search/SKILL.md
[clasohlson]: clasohlson/SKILL.md
[commit]: commit/SKILL.md
[commit-organizer]: commit-organizer/SKILL.md
[context7-skill]: context7-skill/SKILL.md
[conventional-committer]: conventional-committer/SKILL.md
[ecb-rates]: ecb-rates/SKILL.md
[email-mailbox-analyzer]: email-mailbox-analyzer/SKILL.md
[himalaya-email-manager]: himalaya-email-manager/SKILL.md
[hsl]: hsl/SKILL.md
[learn]: learn/SKILL.md
[library]: library/SKILL.md
[mcp-to-skill]: mcp-to-skill/SKILL.md
[motonet]: motonet/SKILL.md
[nano-banana-image]: nano-banana-image/SKILL.md
[power]: power/SKILL.md
[processing-scanned-receipts]: processing-scanned-receipts/SKILL.md
[read-as-markdown]: read-as-markdown/SKILL.md
[rebase-all]: rebase-all/SKILL.md
[secrets-scan]: secrets-scan/SKILL.md
[simplify-skill]: simplify-skill/SKILL.md
[t3-start-thread]: t3-start-thread/SKILL.md
[tokmanni]: tokmanni/SKILL.md
[verkkokauppa]: verkkokauppa/SKILL.md
[youtube-frame-analysis]: youtube-frame-analysis/SKILL.md
[youtube-to-markdown]: youtube-to-markdown/SKILL.md
[youtube-transcription]: youtube-transcription/SKILL.md
[zed-threads]: zed-threads/SKILL.md

[Claude Code]: https://claude.ai/code
[Claude Code skills]: https://docs.claude.com/en/docs/claude-code/skills
[built-badge]: https://img.shields.io/badge/Built_with-Claude_Code-6f42c1?logo=anthropic&logoColor=white
