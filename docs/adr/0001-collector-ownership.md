---
status: superseded by ADR-0002
---

# Collector ownership

Quota numbers come from existing collectors, not from a new API layer and not from `ai-usagebar`. This repo copies the Cursor and Grok collectors, calls packaged Omarchy for Claude and Codex, and owns the OpenCode collector. State files live in `~/.local/state/openusage/` so a disabled `janhoon.agents` install cannot break this plugin.
