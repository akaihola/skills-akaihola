# Contributing to MCP to Skill Converter

Thank you for your interest in contributing! This document outlines the guidelines for reporting bugs, suggesting features, and submitting changes.

## Reporting Issues

If you encounter a bug or have a feature request:

1. Check existing issues to avoid duplicates
2. Provide a clear, descriptive title
3. Include steps to reproduce (for bugs)
4. Attach relevant error messages or logs
5. Mention your Python version and MCP package version

## Submitting Changes

When fixing bugs or adding features:

1. **Update CHANGELOG.md** - Document your changes using the [Keep a Changelog](https://keepachangelog.com) format
2. **Add documentation** - Create or update files in `references/` if needed
3. **Update README.md and SKILL.md** - Reflect any user-facing changes
4. **Test thoroughly** - Test your fix with new MCP server conversions to ensure it works correctly
5. **Keep it focused** - Each pull request should address one concern

## Development Workflow

```bash
# 1. Test the converter with a new MCP server
python scripts/convert_mcp_to_skill.py --mcp-config test-config.json --output-dir test-skill

# 2. Test the generated executor
cd test-skill
uv pip install mcp
python executor.py --list
python executor.py --describe tool_name

# 3. Verify no hangs or errors occur
# 4. Check all documentation is updated
# 5. Submit your changes
```

## Code Style

- Use Python 3.8+ compatible syntax
- Follow PEP 8 style guidelines
- Add docstrings to functions and classes
- Test your code before submitting

## Known Issues

- Early stage project - API may change
- Some complex authentication flows may need adjustments
- Not all MCP servers have been tested

## Future Enhancements

Potential areas for contribution:

- [ ] Support for more complex async patterns
- [ ] Streaming tool support
- [ ] Web-based configuration generator
- [ ] Skill package manager integration
- [ ] Advanced debugging and logging options
- [ ] More comprehensive testing

## Questions?

Feel free to open an issue or discussion to ask questions or get help with implementation.
