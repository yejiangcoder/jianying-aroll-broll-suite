# Codex Roles

## IDEA Codex

Use IDEA Codex for small code edits, review comments, tests, and narrow refactors.

Do not use IDEA Codex for:

- scanning large runtime directories
- opening large draft JSON dumps
- running UAT
- writing real drafts
- batch image generation
- packaging large artifacts

## Desktop Codex

Use Desktop Codex for:

- project migration
- runtime cleanup
- release and dev snapshot packaging
- UAT
- long-running local tool execution
- AI image batch scripts
- report generation

Desktop Codex should default to dry-run for migration and cleanup unless the user explicitly confirms execution.
