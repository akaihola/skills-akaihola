name: context7
description: Dynamic access to context7 MCP server (2 tools)
version: 1.0.0
---

# context7 Skill

This skill provides dynamic access to the context7 MCP server without loading all tool definitions into context.

## Context Efficiency

Traditional MCP approach:
- All 2 tools loaded at startup
- Estimated context: 1000 tokens

This skill approach:
- Metadata only: ~100 tokens
- Full instructions (when used): ~5k tokens
- Tool execution: 0 tokens (runs externally)

## How This Works

Instead of loading all MCP tool definitions upfront, this skill:
1. Tells you what tools are available (just names and brief descriptions)
2. You decide which tool to call based on the user's request
3. Generate a JSON command to invoke the tool
4. The executor handles the actual MCP communication

## Available Tools

- `resolve-library-id`: Resolves a package/product name to a Context7-compatible library ID and returns a list of matching libraries.

You MUST call this function before 'get-library-docs' to obtain a valid Context7-compatible library ID UNLESS the user explicitly provides a library ID in the format '/org/project' or '/org/project/version' in their query.

Selection Process:
1. Analyze the query to understand what library/package the user is looking for
2. Return the most relevant match based on:
- Name similarity to the query (exact matches prioritized)
- Description relevance to the query's intent
- Documentation coverage (prioritize libraries with higher Code Snippet counts)
- Source reputation (consider libraries with High or Medium reputation more authoritative)
- Benchmark Score: Quality indicator (100 is the highest score)

Response Format:
- Return the selected library ID in a clearly marked section
- Provide a brief explanation for why this library was chosen
- If multiple good matches exist, acknowledge this but proceed with the most relevant one
- If no good matches exist, clearly state this and suggest query refinements

For ambiguous queries, request clarification before proceeding with a best-guess match.
- `get-library-docs`: Fetches up-to-date documentation for a library. You must call 'resolve-library-id' first to obtain the exact Context7-compatible library ID required to use this tool, UNLESS the user explicitly provides a library ID in the format '/org/project' or '/org/project/version' in their query.


## Usage Pattern

When the user's request matches this skill's capabilities:

**Step 1: Identify the right tool** from the list above

**Step 2: ALWAYS get tool details first** to obtain correct parameter names and types:

```bash
cd $SKILL_DIR
python executor.py --describe tool_name
```

This loads ONLY that tool's schema, not all tools.

**Step 3: Generate a tool call** using the exact parameter names from Step 2:

```json
{
  "tool": "tool_name",
  "arguments": {
    "param1": "value1",
    "param2": "value2"
  }
}
```

**Step 4: Execute via bash:**

```bash
cd $SKILL_DIR
python executor.py --call 'YOUR_JSON_HERE'
```

IMPORTANT: Replace $SKILL_DIR with the actual discovered path of this skill directory.

## Important Note

You MUST use `--describe` before calling any tool to get the correct parameter names and types. Do not guess parameter names as this will result in errors.

## Examples

### Example 1: Complete workflow

User: "Use context7 to do X"

Your workflow:
1. Identify tool: `resolve-library-id`
2. Get tool details: `python executor.py --describe resolve-library-id`
3. Generate call JSON using exact parameter names from Step 2
4. Execute:

```bash
cd $SKILL_DIR
python executor.py --call '{"tool": "resolve-library-id", "arguments": {"param1": "value"}}'
```

### Example 2: Tool details output

```bash
cd $SKILL_DIR
python executor.py --describe resolve-library-id
```

Returns the full schema with parameter names, types, and requirements.

## Error Handling

If the executor returns an error:
- Check the tool name is correct
- Verify you used `--describe` to get the exact parameter names
- Ensure all required arguments are provided
- Check that parameter types match what's expected
- Ensure the MCP server is accessible

Common error: "Invalid arguments for tool" - This usually means you used an incorrect parameter name. Always run `--describe` first to get the correct parameter names.

## Performance Notes

Context usage comparison for this skill:

| Scenario | MCP (preload) | Skill (dynamic) |
|----------|---------------|-----------------|
| Idle | 1000 tokens | 100 tokens |
| Active | 1000 tokens | 5k tokens |
| Executing | 1000 tokens | 0 tokens |

Savings: ~-400% reduction in typical usage

---

*This skill was auto-generated from an MCP server configuration.*
*Generator: mcp_to_skill.py*
