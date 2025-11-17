# Async Context Manager Fix

## Issue

The MCP `stdio_client()` function returns an async context manager, not a coroutine. The initial converter template incorrectly attempted to `await` it directly, resulting in:

```
TypeError: object _AsyncGeneratorContextManager can't be used in 'await' expression
```

## Root Cause

In the MCP SDK, `stdio_client()` returns an async context manager that should be entered using the async context manager protocol (`__aenter__` and `__aexit__`), not awaited directly.

**Incorrect approach:**
```python
stdio_result = await stdio_client(server_params)  # ❌ Wrong
```

**Correct approach:**
```python
stdio_transport = stdio_client(server_params)  # Get the context manager
read_stream, write_stream = await stdio_transport.__aenter__()  # Enter it
```

## Solution

The converter template has been updated to use the proper `async with` pattern for context managers:

### In `scripts/mcp_to_skill_fixed.py`

**Method structure (each method is self-contained):**
```python
async def list_tools(self):
    """Get list of available tools."""
    server_params = self._get_server_params()
    
    # ✅ Fixed: Use async with for proper resource management
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            response = await session.list_tools()
            return [
                {
                    "name": tool.name,
                    "description": tool.description
                }
                for tool in response.tools
            ]
```

**Key improvements:**
- Each method creates a fresh connection using `async with`
- No shared state between calls (removed `self.session` and `self.stdio_transport`)
- Automatic resource cleanup when exiting the context
- No need for manual `connect()` or `close()` methods

## Implementation

The fix is automatically applied through the following changes:

1. **Local Fixed Template:** `scripts/mcp_to_skill_fixed.py`
   - Contains the corrected async context manager handling
   - Generated during skill creation

2. **Smart Converter Logic:** `scripts/convert_mcp_to_skill.py:87-117`
   - Checks for local fixed version first
   - Falls back to downloading from GitHub if needed
   - Ensures all new conversions use the fix

## Verification

To verify a skill has the fix applied, check that the generated `executor.py` contains:

```python
async with stdio_client(server_params) as (read_stream, write_stream):
    async with ClientSession(read_stream, write_stream) as session:
```

NOT:
```python
stdio_result = await stdio_client(server_params)  # ❌ Broken - original upstream bug
```

OR:
```python
self.stdio_transport = stdio_client(server_params)
read_stream, write_stream = await self.stdio_transport.__aenter__()  # ❌ Causes hangs
```

## Impact

- ✅ All skills generated after this fix automatically include the correction
- ✅ No additional setup or manual fixes needed
- ✅ Executor.py files now properly manage async context managers
- ✅ Clean shutdown and resource cleanup guaranteed

## References

- MCP Python SDK: https://github.com/modelcontextprotocol/python-sdk
- Python Async Context Managers: https://docs.python.org/3/reference/compound_stmts.html#async-with
- Original Issue: Context manager not properly awaited in executor

## Testing

Generated executors with this fix can be tested:

```bash
cd skill-directory
python executor.py --list  # Lists available tools
python executor.py --describe tool_name  # Gets tool schema
python executor.py --call '{"tool": "tool_name", "arguments": {...}}'  # Calls a tool
```
