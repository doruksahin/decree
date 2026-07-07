# Health Signals — governance & coherence drift

> **TL;DR.** `decree health` (alias `decree stale`) reports four signals derived
> from the SQLite index and git history. Three are **findings** that exit `1`
> (stale decisions, ungoverned hotspots, dead governance); one is **advisory**
> and always exits `0` (suggested governance). All are read-only, deterministic,
> and **never** feed `why()` / `intent-check`. The same payload reaches agents
> verbatim through the MCP `health` tool, and `decree ddd` prints the two
> governance-drift counts as a lifecycle hint.

This is the operational reference. For *why* these signals are trustworthy but
convention-bounded (and why some are advisory), read the
[provenance & determinism model](provenance-model.md).

## The four signals

| Signal | Direction | What it means | Precision | Exit |
|---|---|---|---|---|
| **Stale decisions** | declared paths moved on | A decision's `governs:` files have churned by more than `--threshold-commits` commits since the decision doc itself was last touched. | medium | **1** (finding) |
| **Ungoverned hotspots** | code with no owner | A file changed more than `--threshold-commits` times in the last `--threshold-days` days and **no** decision governs it. | medium | **1** (finding) |
| **Dead governance** | declared ∖ observed | A decision declares a `governs:` path that **no** trailer-linked commit of that decision has ever touched — abandoned or aspirational scope. | **high** | **1** (finding) |
| **Suggested governance** | observed ∖ declared | A decision's own trailer-linked commits **repeat-touch** (≥2 distinct commits) a file it does **not** declare and **no** decision owns — a likely missing `governs:` entry. | lower (advisory) | **0** (advisory) |

The asymmetry is deliberate. **Dead governance** is high-precision (a declared
path either was touched or it wasn't), so it counts as a finding. **Suggested
governance** is the lower-precision inverse, so it is advisory: it never changes
the exit code and an agent must treat it as a *suggestion to consider*, never as
a governance fact.

### Two advisory governance-quality signals

Two further signals report governance *quality* rather than coherence. Both are
advisory — they appear in the JSON (`lifecycle_drift[]`, `broad_governance[]`) and
human output but **never change the exit code**.

| Signal | What it means |
|---|---|
| **Lifecycle drift** | A decision at 100% primary acceptance criteria with commits attached but a still-non-terminal status (`complete_but_not_terminal`), or a terminal-success decision whose governance has since gone stale or dead (`terminal_but_governance_stale` / `_dead`). Status stops signalling maturity when these accumulate. |
| **Broad governance** | A decision whose declared `governs:` surface is broad or overlapping: `governs_count`, the exact-vs-directory split, the governs-to-commits ratio, and how many governed paths another decision also governs (`hot_file_overlap_count`) — the drift from "files owned" toward "files touched". |

## Trust the output honestly

Every governance signal is computed deterministically over **trailer-grade**
input (the `Implements:/Refs:/Fixes:` convention), so the payload carries the
context you need to judge it — never assume:

- `linked_commit_count` (per dead/suggested finding) — how many trailer-linked
  commits the claim rests on. More commits ⇒ firmer basis.
- `observed_path_count` (per suggestion) — total paths those commits touched. A
  decision whose 1 commit touched 100 files is a weak basis (and the repeat-touch
  gate already drops it).
- `unobserved_decisions` — decisions that declare `governs:` but have **no**
  trailer-linked commit. They are silent here by design (unobservable, **not**
  dead). A short governance section can simply mean attribution is thin.
- `observed_as_of` — the index's last sync time. Stale index ⇒ stale signals;
  rebuild first.

## The flow: detect → interpret → act

```
        ┌─ decree index rebuild ─┐        (1) refresh the derived index
        │                        │
        ▼                        │
  decree health --json ──────────┘        (2) detect: read the four signals
        │
        ├─ stale_decisions ───────► review the decision; update it or confirm valid
        ├─ ungoverned_hotspots ───► write an ADR/SPEC for the hot file, or accept it
        ├─ dead_governance ───────► fix the decision's governs: (drop abandoned paths)
        │                            or check whether trailers are missing
        └─ missing_governance ────► (advisory) consider adding the suggested path to
                                     the decision's governs:, or feed it to
                                     `decree migrate governs`
```

**1. Detect.** Rebuild the index so attribution is current, then read the
signals:

```bash
decree index rebuild
decree health --json          # full machine payload (advisory + findings)
decree health                 # human-readable, capped advisory section
decree stale --json           # alias — same payload
```

Agents over MCP call the `health` tool (identical payload); `decree ddd` prints
the dead/suggested counts as a one-line hint without the full report.

**2. Interpret.** Empty findings arrays mean coherence at the given thresholds.
A populated `missing_governance` does **not** imply incoherence — it is advisory.
Weigh each finding against the honesty fields above before acting.

**3. Act, per signal:**

- **Stale decision** → open the decision; either update it to match the code that
  moved on, or confirm it is still correct and leave it.
- **Ungoverned hotspot** → a hot file with no decision is the natural ADR/SPEC
  backlog. Write one (`decree new adr … --bucket concern`) and add the file to its `governs:`, or
  consciously accept that it needs none.
- **Dead governance** → the decision claims a path its commits never touched.
  Either the `governs:` entry is wrong (remove/repoint it) or the work was
  committed without an `Implements:/Refs:/Fixes:` trailer (fix trailer
  discipline — see the [provenance model](provenance-model.md)).
- **Suggested governance** *(advisory)* → the decision keeps editing a file it
  doesn't claim. If it should own that file, add it to the decision's `governs:`.
  This is the *batch* surface; the *point-of-change* counterpart is
  `decree intent-check`/`intent-review --under <decision>`, which surfaces the
  same gap for the decision a governed session works under, at the moment of the
  edit (`governs_gaps`). Never add it blindly — confirm it is a real ownership
  relationship first.

## JSON payload

`decree health --json` and the MCP `health` tool return the same shape:

```json
{
  "stale_decisions": [
    {"decision_id": "SPEC-…", "type": "spec", "last_touched_ts": 0,
     "churn_count": 0, "governed_paths": [{"path": "src/…", "count": 0}]}
  ],
  "ungoverned_hotspots": [
    {"path": "src/…", "commit_count": 0, "since_days": 30}
  ],
  "dead_governance": [
    {"decision_id": "SPEC-…", "paths": ["src/…"], "linked_commit_count": 0}
  ],
  "missing_governance": [
    {"decision_id": "SPEC-…", "linked_commit_count": 0, "observed_path_count": 0,
     "candidates": [{"path": "src/…", "commit_count": 0, "distinct_decisions": 0}]}
  ],
  "unobserved_decisions": ["SPEC-…"],
  "observed_as_of": "2026-06-03T00:00:00+00:00",
  "threshold_commits": 10,
  "threshold_days": 30
}
```

The human view caps the advisory section (top candidates per decision, top
decisions) and states any truncation; `--json` is **uncapped** — the full set is
the machine contract.

## Where this lives

- CLI: `decree health` / `decree stale` — `src/decree/commands/health.py`.
- ddd hint: `decree ddd` — `src/decree/commands/ddd.py` (a fail-safe, pure index
  read; reports zero, never an error, when there is no index).
- MCP: the `health` tool — `src/decree/commands/mcp_server.py` (serialized through
  the same formatter as the CLI, so the two never diverge).
- Index: `observed_governs` — `src/decree/index_db.py`.

## Related

- [Provenance & determinism model](provenance-model.md) — what is guaranteed vs.
  convention, and why suggested governance is advisory.
- [LLM Agent Integration](llm-agent-integration.md) — the full agent loop.
- [Capability Index](index.md) — all decree commands.
