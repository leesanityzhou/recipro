# Recipro

Recipro is a local dual-agent code improvement loop:

- Codex scans a repository and picks small, high-impact improvements.
- Claude implements one improvement at a time.
- Codex reviews each round and feeds findings back until the change passes.
- Recipro can then commit, push, create a PR, and write a daily report.

The initial implementation is intentionally conservative. By default, `config.yaml` runs in `dry_run: true`, so you can verify the setup before allowing repository mutations.

## Layout

```text
recipro/
├─ run.py
├─ config.yaml
├─ recipro/
│  ├─ agents/
│  ├─ core/
│  ├─ config.py
│  ├─ models.py
│  ├─ prompts.py
│  ├─ reporting.py
│  ├─ state.py
│  └─ utils.py
├─ memory/
└─ reports/
```

## Requirements

- Python 3.11+
- `codex` CLI authenticated and available in `PATH`
- `claude` CLI authenticated and available in `PATH`
- `git`
- `gh` if you want automated PR creation or merge

## Configure

Edit [`config.yaml`](/Users/lizhou/recipro/config.yaml):

- `repo_path`: repository Recipro should improve. The default value is a safe placeholder and must be changed before a real run.
- `dry_run`: keep `true` until you trust the prompts and CLI setup
- `push_branch`, `github_auto_pr`, `github_auto_merge`: enable only when you want GitHub automation
- `validation_commands`: optional list such as `["pytest", "npm test"]`

## Run

```bash
python3 run.py
```

Or force a dry run regardless of config:

```bash
python3 run.py --dry-run
```

The run writes a markdown report to `reports/YYYY-MM-DD.md` and stores run history in `memory/state.json`.

## Notes

- Recipro requires a clean target worktree before a non-dry run.
- Each task runs on its own branch created from the starting revision.
- If a task fails after edits have been made, Recipro stops and leaves the branch/worktree intact for inspection instead of resetting anything destructively.
