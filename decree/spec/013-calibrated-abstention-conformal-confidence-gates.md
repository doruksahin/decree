---
date: '2026-05-12'
governs:
- src/decree/eval/gates.py
- src/decree/eval/calibration.py
references:
- PRD-004
status: implemented
---

# SPEC-013 Calibrated Abstention — Conformal Confidence Gates

## Overview

Implements PRD-004 R1 — *calibrated abstention*. Decree retrieval today returns the best-of-K result regardless of how weak the match is. This SPEC adds the principled "no governance found" response: a confidence-gated layer that abstains when no candidate is strong enough, with the threshold *calibrated* (not heuristic) against the SPEC-012 query set.

Three deliverables:

1. **Four new confidence gates** (status / recency / coverage / authorship) layered atop Repowise's three (dominance / identifier-citation / hedge-phrase — to be implemented inline). Each gate produces a scalar score; gates compose into a single nonconformity score.
2. **Conformal calibration** via the `crepes` library (MIT) over the SPEC-012 query set. Output: persisted `prediction_set_threshold` per coverage target (default 90% precision among returned answers). Tunable via `--target-precision` flag during calibration.
3. **New retrieval method `keyword-v1-calibrated`** registered with the SPEC-012 eval harness; SPEC-014 will compose with this. CLI surface: `decree why --with-abstention` opts user-facing queries into the calibrated layer; default behavior unchanged (back-compat).

PM directive carried forward: **leverage OSS, no brittle custom code.**
- `crepes` for split conformal prediction (the standard Python lib for the methodology).
- `scipy` (already in) for thresholding helpers.
- Gates are declarative; each is a tiny pure function reading from the existing IndexDB.

## Technical Design

### Confidence gates (7 total — 3 inline + 4 new)

A gate consumes `(query, top_k_results, db)` and returns a `GateSignal { name: str, score: float, hint: str | None }`. Score in `[0, 1]` where higher = more confident. `hint` (optional) is a human-readable reason emitted if the gate triggers abstention.

| Gate | Inline (Repowise replica) | New (SPEC-013) | Signal |
|---|---|---|---|
| **dominance** | ✓ | | Top score / second score ratio. Saturating at 2× → 1.0. |
| **identifier-citation** | ✓ | | Fraction of query identifiers (path components, symbol names) appearing in retrieved doc's title or governs entries. |
| **hedge-phrase** | ✓ | | Detect hedging in top doc's body ("might", "possibly", "TBD"). Lower → less confident. |
| **status** | | ✓ | Top hit's status is terminal-success (`implemented`, `accepted`) → 1.0; deprecated/superseded/rejected → 0.0; active states (draft/approved/review) → 0.5. |
| **recency** | | ✓ | `1 - (days_since_doc_date / 540)` clamped to [0, 1]. 540 days ≈ 18 months → 0 (per PRD-004 R1). |
| **coverage** | | ✓ | Ratio of governing scope to query scope: query path is exact match in governs → 1.0; prefix → 0.5; no match → 0.1 (only via body text). |
| **authorship** | | ✓ | Days since most recent commit by the doc's author (or any author who touched the doc) on any governed path. Decays linearly to 0 over 365 days. |

Gates implemented in `src/decree/eval/gates.py` as 7 small functions matching `GateFn = Callable[[Query, list[RetrievalRow], IndexDB], GateSignal]`. Composition: weighted geometric mean of all signals (geometric mean ≈ "if any signal is near 0, the composite is near 0" — desirable for veto-style gates). Weights configurable per gate in `eval/calibrations/keyword-v1.json`; default uniform.

### Conformal calibration via `crepes`

`crepes` ships split-conformal classification and regression. We model abstention as a **binary classification**: "should this query return a result or abstain?" with the composite gate signal as the score.

Calibration flow:
1. Load SPEC-012 query set. Split into calibration (60%) and test (40%) sets (deterministic shuffle with seed).
2. For each calibration query: run `keyword-v1`, compute the composite gate signal, label `1` if Recall@1 > 0 else `0`.
3. Pass `(scores, labels)` to `crepes.ConformalClassifier`. Choose threshold for the target precision rate (default 0.9 → at least 90% of returned results are genuinely relevant).
4. Persist threshold + per-gate weights to `eval/calibrations/keyword-v1.json` (JSON schema-validated; pydantic on read).

```python
from crepes import ConformalClassifier
from crepes.extras import binning

cc = ConformalClassifier()
cc.fit(scores_train, labels_train)
prediction_sets = cc.predict_set(scores_test, confidence=0.9)
# Threshold = score below which prediction_set excludes 'relevant=1'
```

If `crepes` API in 2026 differs from this sketch, the implementer adapts. We commit to *using* conformal prediction, not to this exact API.

### `keyword-v1-calibrated` retrieval method

Registered via SPEC-012's `RetrievalMethod` Protocol. Adds three behaviors atop `keyword-v1`:
1. Always runs `keyword-v1` first to get top-K candidates.
2. Computes the 7 gate signals + composite score.
3. If `composite < threshold`: returns `[]` (abstention). Otherwise returns `keyword-v1`'s top-K (no rerank in v1 — calibration only affects the return/abstain decision).

The method exposes `last_abstention_reason() -> str | None` so the CLI and MCP layers can surface *why* it abstained.

### CLI surface

```
decree why <path> [--with-abstention] [--target-precision P] [--json] [--project PATH]
decree refs <id> [--with-abstention] [...]
decree retrieval-eval --calibrate [--target-precision P] [--method M] [...]
```

- `--with-abstention` (on `why`/`refs`) — opt into calibrated method. Without the flag, decree behaves exactly as it does today (back-compat).
- `--target-precision P` (default 0.9 during calibrate; default-read-from-config during query) — desired precision among non-abstain responses.
- `decree retrieval-eval --calibrate` — runs the calibration pipeline against the named method (default `keyword-v1`) and writes `eval/calibrations/<method>.json`.

`decree.why` and `decree.refs` MCP tools gain `with_abstention: bool = False` kwarg.

### Abstention reasons

When the calibrated method returns `[]`, the CLI's human output prints:

```
$ decree why src/api/legacy.py --with-abstention
no governance found (composite confidence 0.34; threshold 0.62)

  signals:
    dominance         1.00  (top score 4.2× second; high)
    identifier-citation 0.20  (only 1 of 4 query identifiers in top hit)
    coverage          0.10  (path not in any governs entry)
    recency           0.85
    status            0.50  (top hit is draft)
    authorship        0.42
    hedge-phrase      0.95

  closest non-abstaining hit: SPEC-099 (would have been returned without --with-abstention)
```

`--json` shape:

```json
{
  "abstained": true,
  "composite_score": 0.34,
  "threshold": 0.62,
  "signals": {"dominance": 1.0, "coverage": 0.1, ...},
  "would_have_returned": ["SPEC-099"]
}
```

### Files touched

- **Create**: `src/decree/eval/gates.py` — 7 gate functions + `GateSignal` dataclass + `composite(signals, weights) -> float`.
- **Create**: `src/decree/eval/calibration.py` — `calibrate_method()` driver wrapping `crepes`; `Calibration` dataclass (threshold + per-gate weights); load/save to JSON.
- **Modify**: `src/decree/eval/methods.py` — add `KeywordCalibrated` method registered as `keyword-v1-calibrated`.
- **Modify**: `src/decree/commands/queries.py` — add `with_abstention` param to `why()` and `refs()`. When set, route through `KeywordCalibrated` and surface abstention reasons.
- **Modify**: `src/decree/commands/eval.py` — add `--calibrate` mode.
- **Modify**: `src/decree/commands/mcp_server.py` — `with_abstention` kwarg on `why` / `refs` tools.
- **Modify**: `src/decree/cli.py` — `--with-abstention`, `--target-precision`, `--calibrate` flag wiring.
- **Modify**: `pyproject.toml` — add `crepes>=0.7`.
- **Create**: `eval/calibrations/.gitkeep` and (post-calibration) `eval/calibrations/keyword-v1.json`.
- **Create**: `tests/test_calibration.py` — unit tests for each gate + calibration logic.
- **Modify**: `tests/test_eval.py` — extend with `keyword-v1-calibrated` regression against `eval/queries.yaml`.

### What this SPEC does NOT do

- **No re-ranking** — calibration only affects return/abstain decision; ordering of returned results is whatever `keyword-v1` produced.
- **No hybrid retrieval** — BM25 + dense + structural is research-frontiers A.1; the ranking gaps SPEC-012 surfaced (umbrella-PRD beats implementing-SPEC) require a different SPEC.
- **No re-calibration on every query** — calibration is offline. `decree retrieval-eval --calibrate` is a once-per-corpus-shift operation.
- **No LLM-based confidence judgments** — gates are deterministic. LLM-judge gates are research-frontiers A.3 / future SPEC.
- **No learned gate weights** — default uniform; user can hand-tune in the JSON. Learning weights from calibration data is a v2 polish.
- **No per-query online learning** — research-frontiers A.4; not in scope.
- **No conformal prediction sets for top-K** — binary abstain/return only. Set-valued prediction for "any of these K decisions might be right" is a future research direction.

## Testing Strategy

### Unit tests (`tests/test_calibration.py`)

For each of the 7 gates:
- A passing case (signal close to 1.0) and a failing case (signal close to 0).
- A deterministic, in-process fixture with controlled IndexDB content.

For composite scoring:
- All gates 1.0 → composite 1.0.
- One gate 0.0 → composite 0.0 (geometric mean veto property).
- Custom weights honored.

For calibration:
- Fit on synthetic `(scores, labels)`, assert threshold falls within expected range.
- Round-trip: save calibration → read → identical thresholds.
- Target-precision parameter changes the threshold monotonically.

For `KeywordCalibrated`:
- High-confidence query → returns same as `keyword-v1`.
- Low-confidence query → returns `[]` with abstention reasons populated.
- `last_abstention_reason()` returns informative human string when abstained.

### Integration tests

- **End-to-end calibration**: tmp corpus + 10-query synthetic set → `--calibrate` writes a valid JSON; subsequent eval reads it.
- **CLI: `decree why --with-abstention`**: low-confidence path → abstention output; high-confidence → results.
- **MCP: `with_abstention=True`**: tool response includes `abstained` field.
- **Real corpus dogfood**: run `decree retrieval-eval --calibrate` on `eval/queries.yaml`. Then run regular eval comparing `keyword-v1` (baseline) and `keyword-v1-calibrated`. Capture coverage-risk numbers in the SPEC-013 completion report.

### Dogfood

- SPEC-013's `governs:` declares the new files after they exist.
- Run `decree why src/api/totally-not-a-thing.py --with-abstention` → expect abstention.
- Run `decree why src/decree/index_db.py --with-abstention` → expect SPEC-003.

## v1 Acceptance Criteria

### Gates

- [x] `src/decree/eval/gates.py` exists with 7 gate functions + `GateSignal` + `composite()`.
- [x] Each gate has the signal shape documented in SPEC.
- [x] Composite uses weighted geometric mean (veto property).
- [x] Weights configurable per-gate via calibration JSON.

### Calibration

- [x] `src/decree/eval/calibration.py` uses `crepes` for split conformal prediction.
- [x] `calibrate_method(method, query_set, target_precision)` returns a `Calibration` dataclass.
- [x] Calibration persisted to `eval/calibrations/<method>.json`, schema-validated by pydantic on read.
- [x] `decree retrieval-eval --calibrate` writes the JSON.

### Calibrated retrieval method

- [x] `KeywordCalibrated` registered as `keyword-v1-calibrated` in `eval/methods.py`.
- [x] Method calls `keyword-v1` for top-K, computes composite gate signal, returns `[]` if below threshold.
- [x] `last_abstention_reason()` returns human-readable string after abstention.

### CLI + MCP

- [x] `decree why <path> --with-abstention` works.
- [x] `decree refs <id> --with-abstention` works.
- [x] `decree retrieval-eval --calibrate` works.
- [x] `--target-precision P` honored end-to-end.
- [x] MCP `why` and `refs` tools accept `with_abstention` kwarg.
- [x] Default behavior of `decree why`/`refs` unchanged (back-compat).

### Eval harness integration

- [x] `keyword-v1-calibrated` appears in `decree retrieval-eval`'s methods list.
- [x] Eval report's ablation table shows `keyword-v1-calibrated` vs `keyword-v1` deltas.
- [x] Coverage-risk numbers reported: at target precision P, what fraction of queries are answered vs abstained?

### Dependencies

- [x] `crepes>=0.7` added to `pyproject.toml`.
- [x] `uv tool install -e . --reinstall` picks up the new dep.

### Tests

- [x] `tests/test_calibration.py` covers all gates + composite + calibration.
- [x] `tests/test_eval.py` extended with `keyword-v1-calibrated` regression.
- [x] Full suite passes (489 baseline + new tests).

### Dogfood

- [x] `eval/calibrations/keyword-v1.json` committed (post-calibration snapshot).
- [x] SPEC-013 completion report includes coverage-risk metrics: at target precision 0.9, X% of queries are answered, Y% abstained; baseline (no abstention) precision Z%.
- [x] SPEC-013's `governs:` declared after implementation.

## What this does NOT do (deferred)

- [ ] Hybrid retrieval (BM25 + dense + structural) — future SPEC under PRD-004 or a successor.
- [ ] LLM-judge confidence gates — research-frontiers A.3.
- [ ] Learned gate weights — v2.
- [ ] Online / active learning — research-frontiers A.4.
- [ ] Conformal prediction sets for top-K — future direction.
- [ ] Per-query auto-recalibration — offline only.

## References

- PRD-004 R1 — what this SPEC implements.
- SPEC-012 — eval harness this SPEC plugs into; query set used for calibration.
- SPEC-005 — `queries.why()` / `queries.refs()` extended with `with_abstention`.
- `crepes` — https://github.com/henrikbostrom/crepes (MIT, the canonical Python conformal prediction library).
- El-Yaniv & Wiener (2010) — *On the Foundations of Noise-free Selective Classification*. The methodological reference.
- Vovk, Gammerman, Shafer (2005) — *Algorithmic Learning in a Random World* (conformal prediction).
- research-frontiers.md E.2 — original framing of calibrated abstention as decree's highest-leverage trust property.
