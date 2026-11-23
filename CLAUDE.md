# CLAUDE.md

@AGENTS.md

## Claude Code

- Start, check and stop the app with this repo's `running-the-stack` skill
  (`.claude/skills/running-the-stack/`), not by hand.
- In a worktree session (`.claude/worktrees/*`), keep Bash isolation-safe: one
  plain command per call with literal paths, no `$(…)` around git, no
  `cd "$X"` or `eval`, and wait on background work with Monitor.
