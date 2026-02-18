# STANDARDS.md - Code Quality & Review Standards

## Pre-Delivery Checklist

Before delivering ANY work to Rob, verify all of these:

### Required
- [ ] Tests run and pass (or documented why they can't)
- [ ] No hardcoded secrets (grep for `sk-`, `api_key`, `token`, `password`, `secret`)
- [ ] No hardcoded absolute paths (use env vars or relative paths)
- [ ] No temp files, status reports, or development artifacts committed
- [ ] `.gitignore` covers: `.env`, `*.db`, `__pycache__/`, `.venv/`, `node_modules/`
- [ ] `.env.example` exists if project uses environment variables
- [ ] README.md exists with: what it is, how to run it, how to configure it
- [ ] Clean git history (no "fix typo" chains — squash if needed)

### For graduated projects (own repo)
- [ ] All of the above, plus:
- [ ] Has its own `.git` with proper remote
- [ ] No references to other projects' paths
- [ ] Self-contained — someone could clone it and run it

## Change Classification

| Type | Examples | Review Level |
|------|----------|-------------|
| **Safe** | Docs, comments, formatting, refactor (no behavior change) | Jarvis self-review |
| **Normal** | New features, bug fixes, dependency updates | Jarvis reviews + runs tests |
| **Risky** | Infra changes, systemd units, auth configs, database migrations | Jarvis reviews + runs tests + applies autonomously. **Notify Rob after** with a summary of what changed and why |
| **Destructive** | Permanent deletes, force pushes, drops tables, removes entire services | ALWAYS ask Rob first |

## Coding Standards

- Python: follow existing project style. Use type hints for public APIs.
- JavaScript/Node: follow existing project style.
- Shell scripts: `set -euo pipefail`. Validate config syntax before writing.
- All projects: prefer editing existing files over creating new ones.
- No over-engineering. Solve the problem, not hypothetical future problems.

## Cross-AI Review

For major architecture decisions or designs:
- Jarvis triggers a cross-review by sending the design to a different AI model/provider
- The reviewer's job: find flaws, missing pieces, over-engineering
- Iterate until both perspectives converge
- This is a MANUAL process — Rob or Jarvis decides when it's needed, not automated

## Secrets Policy

- Secrets NEVER go in repos, markdown files, or STATUS
- Secrets live in: environment variables loaded by systemd services, or `.env` files with strict permissions
- Builders only receive `.env.example` + instructions
- Pre-commit check: `grep -rn 'sk-\|api_key\|secret\|password' --include='*.py' --include='*.js' --include='*.sh' --include='*.json'`
