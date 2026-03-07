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

## Features

- **Flexible backend assignment** — mix and match Claude and Codex per role (planner/builder/critic)
- **Interactive setup** — first run prompts for backend + model selection, then saves preferences for subsequent runs
- **Focus mode** — provide a natural-language directive (any language) and Recipro tailors the entire pipeline to fulfill it
- **Ambient supervisor** — a lightweight background agent that watches all agent output and provides:
  - Intelligent, concise status updates (not mechanical logs)
  - Anomaly detection (stuck agents, loops, quality concerns)
  - Per-role cost estimation with run totals
  - Human-readable run summary at the end
  - Automatic language matching (responds in the same language as your directive)
- **Unlimited review loops** — Builder and Critic iterate until the code passes review, no arbitrary caps
- **Automatic PR creation** — Builder handles the full git workflow (branch, lint, test, commit, push, PR)
- **Daily reports** — markdown reports with improvements, files changed, risks, and manual actions

## Layout

```text
recipro/
├─ run.py                  # Entry point
├─ config.yaml             # Project configuration
├─ recipro/
│  ├─ ambient.py           # Ambient supervisor agent
│  ├─ backends/
│  │  ├─ base.py           # Abstract backend interface
│  │  ├─ codex.py          # OpenAI Codex backend
│  │  └─ claude.py         # Anthropic Claude backend
│  ├─ core/
│  │  ├─ orchestrator.py   # Main pipeline orchestration
│  │  └─ git_tools.py      # Git operations
│  ├─ config.py            # Configuration loading
│  ├─ models.py            # Data models
│  ├─ prompts.py           # All agent prompts
│  ├─ reporting.py         # Report generation
│  ├─ state.py             # Run history persistence
│  └─ utils.py             # Subprocess, streaming, JSON parsing
├─ memory/
│  ├─ state.json           # Run history
│  └─ preferences.json     # Saved backend/model selections
└─ reports/                # Generated reports
```

## Requirements

- Python 3.11+ (no pip dependencies)
- `claude` CLI — `npm install -g @anthropic-ai/claude-code` then `claude login`
- `codex` CLI — `npm install -g @openai/codex` (if using Codex as builder/critic)
- `git` and `gh` (GitHub CLI, for PR creation)
- `OPENAI_API_KEY` env var (for Codex backend and/or ambient agent)
- `GEMINI_API_KEY` env var (optional, for ambient agent)

## Configure

Edit `config.yaml`:

```yaml
repo_path: /path/to/your/repo
max_improvements: 3
focus: |
  Your directive here. Can be any language.
  Multi-line supported.

planner_model:           # e.g. sonnet, opus (default: auto)

critic_backend: codex    # codex or claude
critic_model:            # e.g. o4-mini, gpt-5.4, sonnet
builder_backend: claude  # codex or claude
builder_model:           # e.g. opus, sonnet, o3

require_clean_worktree: true
summarize_report: true
```

## Run

```bash
python3 run.py
```

First run prompts for backend/model selection interactively. Choices are saved to `memory/preferences.json`.

```bash
python3 run.py --reconfigure   # Force re-selection
python3 run.py --dry-run       # Plan only, no repo changes
python3 run.py --no-select     # Skip interactive setup, use config defaults
```

## Notes

- Recipro requires a clean target worktree before a non-dry run.
- Each task runs on its own branch created from the starting revision.
- If a task fails, Recipro stops and leaves the branch intact for inspection.
- Zero external Python dependencies — only uses stdlib + CLI tools.
