"""SPEC-01KT22NMRZZ0ZZ0DQ4N0SJPN9S — prompt templates for `decree migrate governs`.

One module for prompt strings so future LLM-assisted SPECs (e.g., a judge that
re-scores existing `governs:` arrays) can reuse them. v1 ships a single
template: `GOVERNS_PROMPT_TEMPLATE`, used by
`decree.commands.migrate.suggest_governs`.

Design notes:
  - Single string with one `{body}` placeholder; the helper truncates the
    document body to a roughly model-safe length before substitution.
  - The character budget is a v1 heuristic (24000 chars ≈ ~6000 tokens for
    English prose). v2 may swap in tiktoken / model-aware tokenization, but
    paying for that dependency before we have a real overflow case is gold-
    plating per RULE #1.
"""

from __future__ import annotations

# ~6000 tokens at roughly 4 chars/token for English prose. Conservative;
# leaves room for the framing prompt and the JSON response without busting
# the typical 8k-200k context windows.
BODY_CHAR_BUDGET: int = 24_000

GOVERNS_PROMPT_TEMPLATE: str = """\
You are helping migrate a software decision document to a typed `governs:` frontmatter field.

The document below describes a decision (PRD/ADR/SPEC). Identify the repo-relative file paths
that this document *governs* — files whose existence or shape is justified by the decision,
files that this decision's implementation creates or modifies, files that future changes to
this decision would affect.

Look specifically at sections titled:
  - "Files touched"
  - "Affected files"
  - "Scope" / "In scope"
  - "Technical Design"

Rules for the output:
  - Paths must be repo-relative (no leading `/`, no `..`).
  - Skip test files unless the document is specifically about test infrastructure.
  - Skip documentation files (decree/, docs/) unless the document is specifically about
    documentation infrastructure.
  - Use directory paths (ending with `/`) when a document governs a whole subtree.
  - Maximum 12 entries. If more candidates exist, pick the most-load-bearing ones.

Return strictly valid JSON with this shape:
  {{"governs": ["path/one.py", "path/two.py", "path/sub/"],
    "confidence": "high" | "medium" | "low",
    "rationale": "one-sentence explanation"}}

Document body follows:

---

{body}
"""


def build_governs_prompt(body: str) -> str:
    """Render `GOVERNS_PROMPT_TEMPLATE` with the document body truncated.

    Truncation is by characters (`BODY_CHAR_BUDGET`), not tokens — a rough but
    cheap heuristic that keeps v1 dependency-light. If the body is longer than
    the budget we keep the head (where "Overview" / "Files touched" usually
    sit) and append a brief truncation marker so the model knows context was
    cut.
    """
    if len(body) <= BODY_CHAR_BUDGET:
        return GOVERNS_PROMPT_TEMPLATE.format(body=body)
    head = body[:BODY_CHAR_BUDGET]
    return GOVERNS_PROMPT_TEMPLATE.format(body=head + "\n\n[... document truncated for length ...]")


# ── SPEC-01KT22NMS0KTWGNKB36RR7K0JR — conflict-judge prompt ─────────────────────────

# 2000 chars per body excerpt — keeps the full prompt well under the typical
# 8k window even when both decisions have long bodies. Plenty of context for
# the judge to decide "real conflict" vs "complementary".
CONFLICT_JUDGE_BODY_BUDGET: int = 2000

CONFLICT_JUDGE_PROMPT_TEMPLATE: str = """\
Two decisions in this repo's governance corpus both claim to govern the
same file path. Determine whether they are a *real* conflict (they
disagree about how the file should behave) or *complementary* (they
address different aspects of the same file — different layers,
different concerns, different lifecycles).

Context:
  Plan being checked: {plan}
  Shared path: {path}

Decision A: {id_a}
Title: {title_a}
Body excerpt:
{body_a}

Decision B: {id_b}
Title: {title_b}
Body excerpt:
{body_b}

Return strictly valid JSON of the form:
  {{"is_real_conflict": true | false, "reasoning": "one-sentence explanation"}}
"""


def build_conflict_judge_prompt(plan: str, path: str, doc_a: dict, doc_b: dict) -> str:
    """Render ``CONFLICT_JUDGE_PROMPT_TEMPLATE`` for one structural conflict.

    Each input dict is expected to carry ``decision_id``, ``title``, and
    ``body`` keys (any missing key is rendered as an empty string). Each
    body is truncated to ``CONFLICT_JUDGE_BODY_BUDGET`` characters with a
    trailing marker so the model knows context was cut.
    """

    def _truncate(text: str) -> str:
        if not text:
            return ""
        if len(text) <= CONFLICT_JUDGE_BODY_BUDGET:
            return text
        return text[:CONFLICT_JUDGE_BODY_BUDGET] + "\n\n[... body truncated ...]"

    return CONFLICT_JUDGE_PROMPT_TEMPLATE.format(
        plan=plan or "",
        path=path or "",
        id_a=str(doc_a.get("decision_id", "")),
        title_a=str(doc_a.get("title", "")),
        body_a=_truncate(str(doc_a.get("body", ""))),
        id_b=str(doc_b.get("decision_id", "")),
        title_b=str(doc_b.get("title", "")),
        body_b=_truncate(str(doc_b.get("body", ""))),
    )
