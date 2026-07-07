# JSON Contracts

The reference for programmatic consumers of decree (an app, CI step, or agent
that spawns the CLI). It freezes the rules that the `--json` surface guarantees,
the **exit-code contract** (the part most often reverse-engineered), and the
machine-readable error shape.

For the agent loop and the MCP tool surface, see
[llm-agent-integration.md](llm-agent-integration.md). For per-command examples,
see [usage.md](usage.md).

## The rules

1. **`--json` writes the payload to stdout.** Human-readable output (tables,
   logs, the `[prefix] …` lines from `log.py`) goes to **stderr**. A consumer
   reads stdout for data and may ignore stderr entirely.
2. **A non-zero exit code does NOT mean "no JSON".** Most commands print their
   full JSON payload to stdout and *then* return a non-zero code to signal
   findings. **Read stdout regardless of the exit code** (see the exit-code
   contract below). This is the single most important rule.
3. **Shapes are additive.** New keys may be added to a payload over time;
   existing keys are not renamed or removed without a version bump. Consumers
   **must ignore unknown keys** and must not assume a closed set.
4. **Empty arrays are valid answers, not errors.** An empty `matches` /
   `governing_decisions` / `conflicts` / `documents` means "decree abstains —
   nothing applies", not a failure. Do not invent governance to fill them.
5. **No hidden fallbacks.** Query commands fail closed (exit 2) when the SQLite
   index is missing or stale rather than returning best-effort data. Rebuild
   with `decree index rebuild`.

## Exit-code contract

Decree uses three exit codes consistently. The key subtlety is that **`1` is a
findings signal, not a crash** — the JSON is still on stdout.

| Code | Meaning | Is JSON on stdout? |
|------|---------|--------------------|
| `0`  | Clean success — ran, no blocking findings | **Yes** |
| `1`  | Ran successfully **and has findings** — conflicts, dead governance, a failing coverage gate, an unhealthy corpus | **Yes** — read it |
| `2`  | Hard error — bad arguments, missing/unreadable input, malformed config, stale/missing index, or an unexpected internal error | Only as `decree.error.v1` (see below); otherwise stderr only |

**Consumer rule of thumb:** treat `0` and `1` as "I have a valid payload, branch
on its contents"; treat `2` (or empty stdout with a non-zero code) as "the
invocation failed, surface the error". This is exactly how a command like
`intent-check` works: it exits `1` when it finds conflicts/stale governance but
still prints the full verdict JSON, and exits `2` only on a genuine error (e.g.
a bad `--under` id or malformed `--other-active-files`).

## Error contract — `decree.error.v1`

When a command is invoked with `--json` and hits an **unexpected** error, decree
emits a stable error object on **stdout** (and a clean one-line summary on
stderr) instead of leaking a Python traceback, and exits `2`:

```json
{
  "schema": "decree.error.v1",
  "error": {
    "command": "intent-check",
    "kind": "ValidationError",
    "message": "human-readable description of what went wrong"
  }
}
```

- `command` — the decree subcommand that failed (or `null` if unresolved).
- `kind` — the error class name (informational; do not branch on exact values).
- `message` — a human-readable summary. Not a traceback.

Notes:
- This is for *unexpected* errors. Expected, handled error conditions (a missing
  index, a bad id) are reported by the command itself, also with exit `2`.
- **Without `--json`**, the human/developer path is unchanged: the error
  surfaces normally (with its traceback), which is useful when debugging decree
  itself.

## Per-command payloads

Each command's `--json` output is documented by its top-level keys below; nested
shapes follow rule 3 (additive). The authoritative shape is always the live
`--json` output of the installed version.

| Command | Top-level keys | Exit codes |
|---------|----------------|------------|
| `graph --json` | `documents[]` (`id`, `type`, `title`, `relative_path`, `references[]`, `governs[]`), `edges[]` | `0` ok |
| `why <path> --json` | `path`, `matches[]` (governing decisions; empty = abstain) | `0` always (abstention is valid); `2` on missing/stale index |
| `refs <id> --json` | `decision_id`, reverse-reference graph | `0` ok; `1`/`2` on bad id / index |
| `progress --json` | `scope`, `percent`, `done`, `total`, `primary`, `deferred`, `document_count`, `documents[]` | `0` ok; `1` on error |
| `intent-check --json` | `plan`, `planned_files[]`, `governing_decisions[]`, `conflicts[]`, `live_conflicts[]`, `governs_gaps[]`, `stale_governance[]`, `recommended_actions[]`, `under_decision`, `under_error`, `source_changes[]`, `corpus_changes[]`, `generated_artifact_changes[]`, `blocking_findings[]`, `advisory_findings[]`, `corpus_hygiene_findings[]`, `directory_overlaps[]`, `owned_files[]`, `contextual_overlaps[]`, `contradictions[]` | `0` clean; **`1` with full JSON** on conflicts/stale/live-conflicts; `2` on error. The `*_changes`, `*_findings`, `directory_overlaps`, and `--under` framing keys are additive and never change the exit code (ADR-01KWXMRRB44CE78H0659D9WDY7) |
| `intent-review --json` | diff-vs-governance report (same family as intent-check) | `0` clean; `1` with JSON on findings; `2` on error |
| `commit-check --json` | `mode`, `strict`, `min_coverage`, `coverage`, `covered`, `total`, `fraction`, `uncovered[]`, `governed_changes[]`, `exit` | `0` ok; `1` when the gate fails (`--strict`/`--min-coverage`); `2` on error |
| `health --json` | `stale_decisions[]`, `ungoverned_hotspots[]`, `dead_governance[]`, suggested-governance, `lifecycle_drift[]`, `broad_governance[]` | `0` healthy; **`1` when dead governance is found** (JSON still emitted); `2` on error. `lifecycle_drift` and `broad_governance` are advisory and never affect the exit code |
| `stale --json` | stale-decision findings | `0`/`1` (findings)/`2` |
| `ddd --json` | lifecycle assessment + next action | `0`; `1` on error |
| `index verify --json` | index sync status | `0` in sync; `1` drift; `2` error |
| `migrate governs --analyze --json` | `decree.governs-analysis.v1` (analysis for an external agent) | `0` |

## Versioning

Read-model payloads (the per-command shapes above) are **not** individually
version-tagged today — there is a single live contract, kept additive. Two
payloads carry an explicit `schema` field because they are negotiated
handshakes, not read models: `decree.error.v1` (above) and the
`decree.governs-analysis.v1` / `decree.governs-suggestions.v1` pair used by
`migrate governs`. A per-command `schema` version field will be introduced only
if and when a read-model shape needs a breaking change — at which point pinning
guidance will be documented here. Until then, code against the additive contract
and ignore unknown keys.
