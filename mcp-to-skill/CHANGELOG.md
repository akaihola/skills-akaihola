# Changelog

All notable changes to the MCP to Skill Converter are documented in this file.

## [Unreleased]

### Fixed
- **Async Context Manager Fix**: Fixed `TypeError: object _AsyncGeneratorContextManager can't be used in 'await' expression` by properly handling MCP's `stdio_client()` context manager protocol using the `async with` pattern. ([#async-context-fix](references/async_context_manager_fix.md))
  - Each executor method now creates a fresh connection using `async with stdio_client(...)`
  - Removed stateful `connect()` and `close()` methods that caused resource leaks
  - Proper automatic resource cleanup via Python's context manager protocol
  - All generated skills now automatically include this fix
  - Smart fallback system prioritizes local fixed template over GitHub download

### Added
- Local fixed converter template (`scripts/mcp_to_skill_fixed.py`) with async context manager fixes
- Documentation on async context manager handling (`references/async_context_manager_fix.md`)
- Troubleshooting guide for context manager errors in README.md and SKILL.md
- Smart converter logic that uses local fixed template first before falling back to GitHub

### Changed
- `convert_mcp_to_skill.py` now checks for local fixed template before downloading from GitHub
- Improved error messages for context manager related issues

## [1.0.0] - 2024-10-26

### Added
- Initial release
- MCP server to skill conversion
- Progressive disclosure pattern for context savings
- Automatic tool introspection
- SKILL.md generation for Claude
- Executor.py for dynamic tool invocation
- Configuration management
