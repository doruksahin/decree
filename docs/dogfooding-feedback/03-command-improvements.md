# Command Improvements

These are proposed decree command changes derived from the Agentkith evidence.
They are not commitments yet. Each proposal should become a PRD/ADR/SPEC before
implementation.

## 1. Add Finding Severity To `intent-check`

Current exit code:

```txt
0 clean
1 conflicts, stale governance, or live-session overlap
2 command/config error
```

Proposal:

Keep exit codes stable, but add typed severity in JSON and human output:

```txt
blocking_findings[]
advisory_findings[]
corpus_hygiene_findings[]
```

Example classification:

- live-session file overlap: blocking
- missing governance for a code file under active decision: blocking or
  advisory depending on `--under`
- stale contextual decision: corpus hygiene
- broad multi-SPEC overlap with no contradiction evidence: advisory

Why:

Agents can still fail closed, but they can explain why they are proceeding when
only advisory/corpus findings exist.

## 2. Make `--under` First-Class

Proposal:

When `--under SPEC-ID` is provided, render the report around that decision:

```txt
Active decision: SPEC-...
Files owned by active decision: ...
Governs gaps for active decision: ...
Other governing decisions: contextual overlaps
Potential contradictions: ...
```

Recommended action text should change from generic conflict language to
decision-relative language:

```txt
Current:
  resolve_conflict_first: path is governed by SPEC-A, SPEC-B, SPEC-C.

Better:
  contextual_overlap: path is also governed by SPEC-B and SPEC-C.
  active decision SPEC-A governs the path and has no unchecked ACs.
```

If `--under` is absent and multiple decisions govern a hot file, the command
can still report a structural conflict.

## 3. Treat Decree Corpus Files As Corpus Maintenance

Proposal:

`intent-check` should classify planned files under the configured decree
document roots separately from source files:

```txt
corpus_changes[]
source_changes[]
generated_artifact_changes[]
```

For corpus changes:

- do not emit `add_governance` for the decision document itself
- do require `decree lint`
- do require `decree index rebuild` / `verify` after frontmatter or `governs:`
  changes
- warn if generated indexes/reports are edited manually

Why:

Updating a SPEC to reflect a code change is good behavior. The tool should not
make it look ungoverned.

## 4. Add Broad-Governance Health Signal

Proposal:

Add a health signal for decisions whose declared `governs:` list is too broad
or too dense.

Candidate metrics:

```txt
governs_count
hot_file_overlap_count
exact_governs_count
directory_governs_count
governs_to_commits_ratio
```

Example finding:

```txt
SPEC-01KWBZPP... governs 66 paths and overlaps hot files with 2 other voice
SPECs. Consider splitting ownership or moving some paths to contextual docs.
```

This should be advisory, not a merge blocker.

## 5. Add Lifecycle Drift Health Signal

Proposal:

Promote status/progress drift into a clear health category:

```txt
100% primary criteria + draft status + commits attached
terminal status + changed acceptance criteria after report snapshot
implemented status + stale governs gap
```

Example recommendation:

```txt
SPEC-X is 100% complete but still draft. Run `decree status SPEC-X submit` and
`decree status SPEC-X approve/implement`, or move incomplete criteria to a
deferred section.
```

Why:

Status drift directly reduces agent trust in decree output.

## 6. Improve Human Output For Known Noisy States

Proposal:

Make human output show "what to do now" separately from "what to clean later".

Example structure:

```txt
Blocking for this plan:
  none

Proceed with caution:
  path also governed by SPEC-B and SPEC-C

Corpus hygiene:
  SPEC-B is stale
  SPEC-C is 100% complete but draft

Recommended next command:
  decree intent-check --under SPEC-A --files ...
```

The current flat recommendation list makes unrelated cleanup feel like a
precondition for the bugfix.

## 7. Add A Dogfood Fixture Suite

Proposal:

Create test fixtures based on the Agentkith cases:

- one hot ViewModel governed by three complementary decisions
- one shared contract initially ungoverned, then added under the active SPEC
- one planned SPEC document edit
- one draft 100% SPEC
- one broad governs SPEC with 60+ paths

Use these fixtures to prevent future command changes from optimizing for toy
corpora only.

