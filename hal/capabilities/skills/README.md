# HaL Skills

This directory contains built-in skills that extend HaL's capabilities.

## Skill Format

Each skill is a directory containing a `SKILL.md` file with:
- YAML frontmatter (name, description, requires_bins, requires_env, always)
- Markdown instructions for the agent

## Available Skills

| Skill | Description |
|-------|-------------|
| `github` | Interact with GitHub using the `gh` CLI |
| `summarize` | Summarize URLs, files, and YouTube videos |
| `tmux` | Remote-control tmux sessions |
| `skill-creator` | Create new skills |