# Recipro

Autonomous multi-agent code improvement. Point it at a repo, tell it what to do, and it plans, implements, reviews, and ships a PR — no manual intervention.

## Install

```bash
pip install recipro
```

### Prerequisites

- Python 3.11+
- `claude` CLI — `npm install -g @anthropic-ai/claude-code` then `claude login`
- `codex` CLI — `npm install -g @openai/codex` then `codex login` (if using Codex as builder/critic)
- `git` and `gh` (GitHub CLI, for PR creation)
- `OPENAI_API_KEY` or `GEMINI_API_KEY` env var (optional, for ambient supervisor)

## Quick start

```bash
recipro
```

On first run, Recipro walks you through setup:

```
First-time setup:
  Target repo path: /path/to/your/repo
  Planner model: ...
  Critic backend: ...
  Builder backend: ...
  Ambient narrator: ...
  Preferences saved to ~/.recipro/.

What should Recipro focus on?
  > your directive here (or press Enter for general scan)
```

Preferences persist — subsequent runs only ask for the focus directive.

## Usage

```bash
recipro                          # Run: setup (if first time) → focus → execute
recipro --reconfigure            # Re-do setup (change repo, backends, models)
recipro --set KEY=VALUE          # Change a config setting
recipro --dry-run                # Plan only, no repo changes
recipro --clean                  # Reset dirty worktree from a failed run
```

### Focus directive

Each run asks what Recipro should focus on. You can write in any language:

```
What should Recipro focus on?
  > Add input validation to all API endpoints
```

Press Enter with no input for a general code scan (finds bugs, security issues, maintainability improvements).

### Changing settings

Backend, model, and repo path — re-run interactive setup:

```bash
recipro --reconfigure
```

Config toggles — set directly from CLI:

```bash
recipro --set verbose=true           # Show raw agent output
recipro --set max_improvements=3     # Tasks per run
recipro --set auto_merge=true        # Squash-merge PRs automatically
recipro --set require_clean_worktree=false
```

### Cleaning up

If a run fails and leaves the target repo in a dirty state:

```bash
recipro --clean
```

This discards uncommitted changes, switches back to main, and deletes all `recipro/*` task branches.

## How it works

```
┌─────────┐     ┌─────────┐     ┌─────────┐       ┌─────────┐     ┌─────────┐
│ Planner │ ──▶ │ Builder │ ──▶ │ Critic  │ ──▶   │ Builder │ ──▶ │ Builder │
│ (Claude)│     │         │     │         │       │ Verify  │     │ Push PR │
│ Scan &  │     │ Implement│    │ Review  │       │ Lint &  │     │ Branch, │
│ plan    │     │ changes │  ◀──│ findings│  ◀──  │ test    │     │ commit, │
│ tasks   │     │         │     │         │       │         │     │ push    │
└─────────┘     └────┬────┘     └─────────┘       └────┬────┘     └─────────┘
                     │              │   │              │
                     └──── loop ────┘   │ fix failures │
                                        └──────────────┘
                                         ┌──────────┐
                  Observing all of ───▶  │ Ambient  │
                  the above              │ Agent    │
                                         │ (GPT/    │
                                         │ Gemini)  │
                                         └──────────┘
```

1. **Planner** (Claude) — scans the repo and breaks the directive into concrete tasks
2. **Builder** (Claude or Codex) — implements each task
3. **Critic** (Claude or Codex) — reviews changes, sends findings back to Builder (loops until pass)
4. **Builder** — runs lint and tests; if anything fails, fixes and re-runs (loops until pass)
5. **Builder** — creates branch, commits, pushes, opens PR
6. **Ambient Agent** (GPT or Gemini) — monitors all agent output in the background, provides status updates, cost tracking, and anomaly detection

## Features

- **Mix and match backends** — assign Claude or Codex independently to each role (planner/builder/critic)
- **Focus mode** — natural-language directive each run, any language. No directive = general scan
- **Ambient supervisor** — background agent watching all output, reporting status, catching stuck loops, estimating costs
- **Automatic PR creation** — full git workflow: pull latest, branch, lint, test, commit, push, PR
- **Auto-merge** — optionally squash-merge PRs after creation
- **Worktree cleanup** — `--clean` resets a dirty repo left by a failed run
- **Zero dependencies** — pure Python stdlib

## Configuration

`~/.recipro/config.yaml` (auto-created on first run, editable via `recipro --set`):

```yaml
max_improvements: 1            # Tasks per run
require_clean_worktree: true   # Require clean git state before run
auto_merge: false              # Auto squash-merge PRs after creation
verbose: false                 # Show raw agent streaming output
```

Backend/model selections are in `~/.recipro/memory/preferences.json`, managed via `recipro --reconfigure`.

## Data directory

```text
~/.recipro/
├─ config.yaml             # Settings
├─ memory/
│  ├─ preferences.json     # Repo path, backend/model selections
│  └─ state.json           # Run history
└─ reports/                # Per-run operational reports
```

## Notes

- Recipro pulls the latest code (`git pull`) before each run.
- Each task runs on its own branch created from the starting revision.
- If a task fails, Recipro stops and leaves the branch for inspection. Use `--clean` to reset.
- The ambient agent auto-disables after 3 consecutive API failures.
