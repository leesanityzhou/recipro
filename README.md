# Recipro

Recipro is an autonomous multi-agent code improvement system. It reads your codebase, plans improvements, implements them, reviews the changes, and ships pull requests — all without manual intervention.

## How it works

```
┌─────────┐     ┌─────────┐     ┌─────────┐     ┌─────────┐
│ Planner │ ──▶ │ Builder │ ──▶ │ Critic  │ ──▶ │ Builder │
│ (Claude)│     │         │     │         │     │ Push PR │
│ Scan &  │     │ Implement│    │ Review  │     │ Lint,   │
│ plan    │     │ changes │  ◀──│ findings│     │ test,   │
│ tasks   │     │         │     │         │     │ commit  │
└─────────┘     └────┬────┘     └─────────┘     └─────────┘
                     │              │
                     └──── loop ────┘
                                        ┌──────────┐
                  Observing all of ───▶  │ Ambient  │
                  the above              │ Agent    │
                                         │ (GPT/   │
                                         │ Gemini) │
                                         └──────────┘
```

1. **Planner** (Claude, plan mode) — scans the repo and breaks the user's directive into concrete tasks
2. **Builder** (configurable: Claude or Codex) — implements each task by editing code
3. **Critic** (configurable: Claude or Codex) — reviews changes, sends findings back to Builder
4. **Builder** again — runs lint/tests, creates branch, commits, pushes, opens PR
5. **Ambient Agent** (GPT or Gemini) — monitors all agent output in the background, provides intelligent status updates, cost tracking, anomaly detection, and a run summary

## Install

```bash
pip install recipro
```

### Prerequisites

- Python 3.11+
- `claude` CLI — `npm install -g @anthropic-ai/claude-code` then `claude login`
- `codex` CLI — `npm install -g @openai/codex` then `codex login` (if using Codex as builder/critic)
- `git` and `gh` (GitHub CLI, for PR creation)
- `OPENAI_API_KEY` or `GEMINI_API_KEY` env var (optional, enables the ambient supervisor agent)

## Quick start

```bash
recipro
```

On first run, Recipro walks you through setup:

```
First-time setup:
  Target repo path: /path/to/your/repo
  Planner (claude) model: ...
  Critic backend: ...
  Builder backend: ...
  Ambient narrator: ...
  Preferences saved to ~/.recipro/.

What should Recipro focus on?
  > your directive here (or press Enter for general scan)
```

Preferences are saved to `~/.recipro/`. Subsequent runs skip setup and only ask for the focus directive.

```bash
recipro --reconfigure   # Re-do setup (change repo, backends, models)
recipro --dry-run       # Plan only, no repo changes
recipro --no-select     # Skip all prompts, use saved preferences
```

## Features

- **Flexible backend assignment** — mix and match Claude and Codex per role (planner/builder/critic)
- **Interactive setup** — first run prompts for repo path, backend + model selection; preferences persist across runs
- **Focus mode** — provide a natural-language directive (any language) each run, and Recipro tailors the entire pipeline to fulfill it. No directive = general code scan
- **Ambient supervisor** — a lightweight background agent that watches all agent output and provides:
  - Intelligent, concise status updates (not mechanical logs)
  - Anomaly detection (stuck agents, loops, quality concerns)
  - Per-role cost estimation with run totals
  - Human-readable run summary at the end
  - Automatic language matching (responds in the same language as your directive)
- **Unlimited review loops** — Builder and Critic iterate until the code passes review, no arbitrary caps
- **Automatic PR creation** — Builder handles the full git workflow (branch, lint, test, commit, push, PR)
- **Auto-merge** — optionally squash-merge PRs automatically after creation
- **Zero dependencies** — pure Python stdlib, no pip packages required

## Configuration

Settings live at `~/.recipro/config.yaml` (auto-created on first run):

```yaml
max_improvements: 1            # Tasks per run
require_clean_worktree: true   # Require clean git state before run
auto_merge: false              # Auto squash-merge PRs after creation
```

Everything else (repo path, backends, models, ambient agent) is in `~/.recipro/memory/preferences.json`, managed by the interactive setup.

## Data directory

All Recipro state lives in `~/.recipro/`:

```text
~/.recipro/
├─ config.yaml             # Base settings
├─ memory/
│  ├─ preferences.json     # Saved repo path, backend/model selections
│  └─ state.json           # Run history
└─ reports/                # Generated markdown reports
```

## Notes

- Recipro requires a clean target worktree before a non-dry run (configurable).
- Each task runs on its own branch created from the starting revision.
- If a task fails, Recipro stops and leaves the branch intact for inspection.
- The ambient agent auto-disables after 3 consecutive API failures (rate limits, etc).
