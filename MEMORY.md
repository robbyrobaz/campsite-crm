# MEMORY.md - Long-Term Memory

## Model Strategy

**Cost-efficiency rule:** Use Haiku for regular automated tasks, Sonnet for heavy reasoning.

- **Default (Haiku):** All cron jobs, heartbeats, periodic checks, routine automation
- **Heavy tasks (Sonnet):** Complex reasoning, code reviews, strategy analysis, research — override with `model=sonnet` when you know it needs depth
- **Alias:** Use `sonnet` shorthand instead of full `anthropic/claude-sonnet-4-5`

Apply this to all new automation: default to haiku unless the task explicitly requires nuanced thinking.
