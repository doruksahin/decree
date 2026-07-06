# Agentkith Evidence

This page records concrete situations from Agentkith dogfooding. The examples
are intentionally specific so the follow-up work can be tested against real
cases instead of abstract workflow preferences.

## Case 1: Canvas Toolbar Dictation Target

Commit:

```txt
0d204b271 fix(app): route toolbar dictation to retained orchestrators
```

Observed issue:

```txt
The canvas toolbar microphone showed "Launch an orchestrator before dictating a
command" even when an orchestrator was open in a pop-out window.
```

Actual root cause:

```txt
The root renderer only checked its local OrchestratorCockpitViewModel
firstOrchestrator. Pop-out activity in main carried orchestrator snapshots, but
the aggregate activityChanged event dropped the first target before broadcasting
to the root renderer.
```

Where decree helped:

- The existing voice SPEC described the intended canvas toolbar rule: target
  the first orchestrator and keep working when the cockpit panel/window is not
  mounted.
- `why` showed that renderer cockpit files were governed by voice-related
  decisions, which forced the fix to stay within the voice/cockpit boundary.
- Updating the SPEC before implementation made the shared/main activity
  contract change explicit.

Where decree hurt:

- `why app/src/shared/orchestrator-cockpit-window/contracts.ts` initially
  returned no governing decision even though the correct fix needed that shared
  contract.
- After adding `governs:` entries, `intent-check` still exited 1 because the
  hot ViewModel file was governed by three decisions:

  ```txt
  SPEC-01KWT2KV1XQKS4JGYZS1KTYFWN  LLM CLI reasoning effort launch controls
  SPEC-01KWHN9PTEWNDP19KRQQM3TDHG  In-app voice dictation v1
  SPEC-01KWBZPP3NZ08D2MNPEBRPRC80  Push-to-talk orchestrator voice command first slice
  ```

- The actionable decision was `SPEC-01KWBZPP3NZ08D2MNPEBRPRC80`, but
  `intent-check` had no concise way to say "work under this decision; treat the
  other two as contextual overlap unless their acceptance criteria contradict
  the plan."

## Case 2: Pop-out Hook Setup Trust Boundary

Commit:

```txt
f46ccc6d0 fix(app): trust cockpit popouts for provider hooks
```

Observed issue:

```txt
Claude/Codex hook setup showed "IPC sender WebContents is not trusted" from a
second orchestrator window, even when hooks were already installed or should
have been repairable from that window.
```

Actual root cause:

```txt
The pop-out BrowserWindow webContents was trusted for terminal operation but
not for Claude/Codex hook setup IPC.
```

Where decree helped:

- The provider hook readiness SPEC made "do not launch unless provider hooks
  are ready" explicit.
- That forced the fix to happen in main IPC trust wiring, not in the renderer
  dialog by suppressing the error.

Where decree hurt:

- The main composition file is a natural overlap point for many decisions.
  Structural overlap is expected there, but current conflict output does not
  distinguish composition-root overlap from contradictory product intent.

## Case 3: Broad Voice Dictation Governance

Relevant command output from Agentkith:

```txt
SPEC-01KWBZPP3NZ08D2MNPEBRPRC80 Push-to-talk orchestrator voice command first slice
Governs: 66 paths

SPEC-01KWHN9PTEWNDP19KRQQM3TDHG In-app voice dictation v1
Governs: 60 paths
```

Observed issue:

```txt
Both SPECs govern parts of the same voice/dictation surface. That is not
automatically wrong, but it makes hot files such as OrchestratorCockpitViewModel
look conflicted even when one SPEC is a first slice and another is an extraction
or evolution slice.
```

Impact:

- Agents see a conflict but not the relationship type.
- Humans must remember which SPEC is authoritative for the current behavior.
- `governs:` becomes partly "files touched during the feature" instead of only
  "files owned by this decision."

## Case 4: Draft Documents With Completed Work

Relevant Agentkith progress signal:

```txt
SPEC-01KWHN9PTEWNDP19KRQQM3TDHG  draft  100% (14/14 primary)
SPEC-01KWBZPP3NZ08D2MNPEBRPRC80  draft  progress not shown, but active code ships
```

Observed issue:

```txt
The work may be functionally shipped, but the document lifecycle still says
draft. Agents then receive stale or confusing guidance: is this still planning,
or is it established behavior?
```

Impact:

- Status stops communicating maturity.
- `progress` and `intent-check` become less useful for prioritizing cleanup.
- Reviewers must inspect commits and code to infer reality.

## Case 5: Governance Gap For A SPEC Document Itself

During the toolbar dictation fix, `intent-check` included the edited SPEC file
in the planned file list and recommended:

```txt
add_governance: decree/spec/.../spec-01kwbzpp...md has no governing decision.
```

Observed issue:

```txt
Editing a decision document to update its own technical design is normal
decision maintenance. It should be represented as corpus maintenance, not as a
missing `governs:` target.
```

Impact:

- Agents get a recommendation that they should not follow.
- The output makes valid SPEC maintenance look like missing governance.

