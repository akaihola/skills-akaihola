

<skills_system priority="1">

## Available Skills

<!-- SKILLS_TABLE_START -->
<usage>
When users ask you to perform tasks, check if any of the available skills below can help complete the task more effectively. Skills provide specialized capabilities and domain knowledge.

How to use skills:
- Invoke: Bash("openskills read <skill-name>")
- The skill content will load with detailed instructions on how to complete the task
- Base directory provided in output for resolving bundled resources (references/, scripts/, assets/)

Usage notes:
- Only use skills listed in <available_skills> below
- Do not invoke a skill that is already loaded in your context
- Each skill invocation is stateless
</usage>

<available_skills>

<skill>
<name>mcp-to-skill</name>
<description>Convert any MCP server into a Claude Skill with 90% context savings. Use this skill when converting an MCP server to a skill to reduce context usage and improve performance.</description>
<location>project</location>
</skill>

<skill>
<name>context7</name>
<description>Dynamic access to context7 MCP server (2 tools)</description>
<location>global</location>
</skill>

<skill>
<name>secrets-management</name>
<description>Manage API keys, tokens, passwords, and credentials using age encryption and git versioning. Use when the user needs to store, retrieve, rotate, edit, or sync secrets securely across devices. Includes commands for the secrets CLI wrapper.</description>
<location>global</location>
</skill>

<skill>
<name>skill-creator</name>
<description>Guide for creating effective skills. This skill should be used when users want to create a new skill (or update an existing skill) that extends Claude's capabilities with specialized knowledge, workflows, or tool integrations.</description>
<location>global</location>
</skill>

</available_skills>
<!-- SKILLS_TABLE_END -->

</skills_system>

## Recent Fixes & Updates

### Async Context Manager Fix for MCP-to-Skill Converter

The MCP-to-Skill converter has been updated to properly handle async context managers in generated executor scripts. This resolves the following error that could occur with some MCP servers:

```
TypeError: object _AsyncGeneratorContextManager can't be used in 'await' expression
```

**What was fixed:**
- Proper handling of `stdio_client()` context manager protocol
- Correct resource cleanup in executor close methods
- All newly generated skills automatically include this fix

**For details, see:** `mcp-to-skill/references/async_context_manager_fix.md`

### Skills Using the Fix

- ✅ `context7` - Now properly handles async MCP communication

## Package Management

### Python Package Installation

IMPORTANT: Always use `uv pip install` instead of `pip install` for installing Python packages in this project.

Example:
```bash
# Correct
uv pip install pytest-asyncio

# Incorrect
pip install pytest-asyncio
```

This ensures proper package management and compatibility with the project's virtual environment setup.
