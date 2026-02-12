# OpenClaw 2nd Brain + Blofin Workspace

This repository now has a clear split between **personal knowledge files** and **runtime apps/services**.

## Top-level layout

- `brain/` — personal 2nd-brain knowledge base (notes + templates)
  - `brain/inbox/`
  - `brain/projects/`
  - `brain/decisions/`
  - `brain/learnings/`
  - `brain/weekly/`
  - `brain/templates/`
- `runbooks/` — operational procedures
- `scripts/` — automation helpers (backup, installers, note scaffolding)
- `config/` — local config snippets
- `systemd/` — service units/timers
- `blofin-stack/` — live monitor/API stack
- `blofin-dashboard/` — dashboard frontend
- `kanban-dashboard/` — local ops kanban frontend
- `blofin-research/` — research workspace
- `external-repos/` — untracked upstream clones/sandboxes
- `memory/` + `MEMORY.md` pattern (agent memory continuity)

## 2nd-brain workflow

1. **Capture** quickly in `brain/inbox/`
2. **Distill** into `brain/projects/`, `brain/decisions/`, `brain/learnings/`
3. **Review** weekly in `brain/weekly/`

## Quick commands

Create a session summary:

```bash
./scripts/new-session-summary.sh "short-title"
```

Create/update a project note:

```bash
./scripts/new-project-update.sh "project-slug"
```

Start weekly review note:

```bash
cp brain/templates/weekly-review.md \
  "brain/weekly/$(date +%F)-weekly-review.md"
```

## Backup references

- 2nd-brain offsite backup runbook: `runbooks/offsite-backup-2nd-brain.md`
- Auto code backup sync: `runbooks/auto-code-backup-sync.md`
- Blofin stack backup/restore: `runbooks/blofin-stack-backup-restore.md`

## Live local URLs

- Blofin Dashboard: `http://127.0.0.1:8766`
- Blofin Metrics API: `http://127.0.0.1:8766/api/metrics`
- Ops Kanban Dashboard: `http://127.0.0.1:8767`
