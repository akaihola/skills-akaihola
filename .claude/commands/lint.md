---
description: Run linters on the code. Optional paths to lint as arguments.
allowed-tools: Bash(uv run pytest *:*)
model: anthropic/claude-haiku-4-5
---

Look at these linting errors:

!`graylint -r origin/main... $ARGUMENTS`

Fix the linting error which in your opinion is the highest priority among the above.
Then run `uv run pytest` for the directory of the skill modified,
for example if `someskill/scripts/somescript.py` was modified,
run `uv run pytest someskill/`.
