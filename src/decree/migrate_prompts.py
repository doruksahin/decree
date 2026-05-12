"""SPEC-011 — prompt templates for `decree migrate governs`.

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
# the typical 8k–200k context windows.
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

Return strictly valid JSON of the form:
  {{"governs": ["path/one.py", "path/two.py", "path/sub/"], "confidence": "high" | "medium" | "low", "rationale": "one-sentence explanation"}}

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
    return GOVERNS_PROMPT_TEMPLATE.format(
        body=head + "\n\n[... document truncated for length ...]"
    )
