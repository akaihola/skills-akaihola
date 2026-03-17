# Search the Library

## Context
Find entries in the library catalog by keyword.

## Input
One or more keywords to search for.

## Steps

### 1. Read the Catalog
- Read `~/prg/skills-akaihola/library/library.yaml`
- No git pull needed for search (catalog is already local)

### 2. Search
Search across all fields: `name`, `description`, `source`, `requires`.
Match if any keyword appears (case-insensitive) in any field.

### 3. Display Results
Show matching entries grouped by type (skills / agents / prompts).
For each match, show: name, description, source, and install status (as in `list`).

If no results: suggest `/library list` to browse everything.
