# Knowledge Base (v1)

Lightweight 2nd-brain for OpenClaw work across projects.

## Structure

- `inbox/` — quick raw captures (notes, links, ideas). Low friction.
- `projects/` — project-level files and updates.
- `decisions/` — decision records (what/why/tradeoffs).
- `learnings/` — lessons, patterns, mistakes, wins.
- `runbooks/` — repeatable procedures and checklists.
- `weekly/` — weekly review snapshots.
- `templates/` — reusable markdown templates.
- `scripts/` — helper scripts to create consistent notes.

## Workflow (Capture -> Distill -> Link)

1. **Capture** (fast)
   - Drop rough notes into `inbox/`.
   - Use `scripts/new-session-summary.sh` after meaningful sessions.

2. **Distill** (daily/weekly)
   - Move high-value items from `inbox/` into:
     - `projects/` for project state
     - `decisions/` for non-trivial choices
     - `learnings/` for reusable insight

3. **Link** (make it findable)
   - In every distilled note, add links to:
     - related project file in `projects/`
     - related task/ticket/reference
     - upstream source note from `inbox/` or session summary

## Quick Start

### 1) Create a session summary

```bash
./knowledge-base/scripts/new-session-summary.sh "short-title"
```

### 2) Create/update a project note

```bash
./knowledge-base/scripts/new-project-update.sh "project-slug"
```

### 3) Weekly review

```bash
cp knowledge-base/templates/weekly-review.md \
  "knowledge-base/weekly/$(date +%F)-weekly-review.md"
```

### 4) Offsite backup (2nd brain)

```bash
cp knowledge-base/scripts/offsite-backup.env.example \
  knowledge-base/scripts/offsite-backup.env
./knowledge-base/scripts/offsite-backup.sh check-config
./knowledge-base/scripts/offsite-backup.sh backup
./knowledge-base/scripts/offsite-backup.sh verify
```

See runbook: `knowledge-base/runbooks/offsite-backup-2nd-brain.md`

## Conventions

- Use `YYYY-MM-DD` in filenames for chronology.
- Keep notes short and operational.
- Prefer one project file per active project (`projects/<slug>.md`).
- Capture first, polish later.
