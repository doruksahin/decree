---
status: approved
date: 2026-01-15
---

# PRD-001 Task Management CLI

## Problem Statement

Developers track tasks in too many places — sticky notes, Notion, Jira, text files, terminal history. Context switches between tools break flow. A CLI tool that lives where developers already work (the terminal) would reduce friction and keep tasks close to the code they relate to.

The target user is a solo developer or small team (2-5) who wants lightweight task tracking without leaving the terminal. Not a Jira replacement — a complement for personal and small-team workflows.

## Requirements

- Create, list, update, and delete tasks from the command line
- Tasks persist locally (no account, no server, works offline)
- Each task has: title, status (todo/doing/done), optional priority (low/med/high), optional due date
- Filter and sort by status, priority, or due date
- Output is human-readable in the terminal and machine-parseable (JSON flag)
- Storage must survive across terminal sessions and machine reboots
- Sub-second response time for all operations (no perceptible lag)

## Success Criteria

- A new user can `task add "Fix login bug" --priority high` → `task list` and see the result in under 10 seconds of learning
- Workflow: `task add` → `task do 1` → `task done 1` covers 90% of daily use
- `task list --json | jq '.[] | select(.priority == "high")'` works for scripting
- Data is not lost on crash (atomic writes)
- Works on macOS and Linux without extra dependencies

## Scope

**In scope:** Single-user CLI, local storage, basic filtering, JSON output.

**Out of scope:** Multi-user sync, web UI, calendar integration, natural language parsing, recurring tasks. These are valid features but not for v1 — they can be separate PRDs if demand emerges.
