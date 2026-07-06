# Executive Summary

Decree helped during live Agentkith work, but the current agent loop has too
many false blockers and too little prioritization.

The strongest positive signal: decree pushed the agent away from local UI
patches and toward the actual owning contract. In the canvas toolbar dictation
bug, the cheap fix would have been enabling the microphone when any activity was
visible. The correct fix was to extend the `orchestrator-cockpit-window`
activity contract so the root renderer received the first dictation target.

The strongest negative signal: `intent-check` currently mixes real blockers,
corpus hygiene debt, and expected multi-SPEC overlap into the same exit-1
bucket. An agent can still proceed with judgment, but the tool output does not
make that judgment easy or deterministic.

## What Is Working

- `why` gives a fast, concrete answer for governed code paths.
- `refs` exposes large ownership surfaces that humans would not remember.
- `intent-check` catches missing governance before code is written.
- The `governs:` model creates a useful forcing function: "which decision owns
  this change?"
- The explicit index model prevents stale query claims from being hidden behind
  automatic rebuilds.

## What Is Not Working

- Multiple decisions often govern the same hot file, and decree reports that as
  a conflict without enough context to decide whether it is real.
- Large SPECs with 60+ governed paths reduce ownership signal.
- Finished work often remains `draft`, so progress and intent output reads like
  unfinished work even when implementation is already shipped.
- `intent-check` can recommend adding governance for the decision document being
  edited, which is not useful for normal SPEC maintenance.
- The default skill workflow says "resolve stale/conflict first" too broadly for
  live bugfix work.

## Direction

Keep decree. Do not make it less strict by hiding findings. Instead, make the
findings more typed:

- blocking vs advisory
- current-plan vs corpus-hygiene
- active-decision gap vs unrelated stale decision
- structural overlap vs real semantic conflict
- code ownership vs decision-document maintenance

The goal is not fewer warnings. The goal is warnings an agent can act on without
guessing.

