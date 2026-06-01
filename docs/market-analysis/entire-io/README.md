# entire.io — Worldview Analysis for decree

Sources read: https://entire.io, https://entire.io/company, https://entire.io/vision,
https://entire.io/blog/hello-entire-world, https://entire.io/blog/the-entire-cli-how-it-works-and-where-its-headed,
https://docs.entire.io/overview, https://entire.io/news/former-github-ceo-thomas-dohmke-raises-60-million-seed-round,
https://dev.to/huoru/we-have-code-review-we-need-intent-review-1i38

---

## The Central Claim

Entire is built on one conviction: **the gap between intent and code is the foundational engineering artifact, and every developer tool before theirs left it unaddressed.**

Thomas Dohmke frames this historically. "The entire software ecosystem is being bottlenecked by a manual system of production that was never designed for the era of AI." He draws the assembly-line analogy: automotive production replaced craft with coordinated, traceable manufacturing steps. Software faces the same phase transition — not an upgrade to existing workflows, a replacement of the substrate.

The distinction for decree: entire.io is not building a better notebook for engineers. They are building the traceability layer that should have existed all along, now made urgent because agents write code faster than the reasoning behind it can be captured.

---

## What They Think Is Actually Breaking Down

The problem they have named is structural: **the production artifact (code) and the production rationale (why this code, what was rejected) are stored in different systems with no durable link.**

From the CLI blog: "Git tells you who committed the code. Entire shows how it was built." From the vision page: "every decision can be traced back to intent, not just code commits." Outcomes without traceable rationale are not auditable, not learnable, and not safe to hand to an agent building on top of them.

The failure mode is specific. From the intent-review post: Claude Code confidently rebuilt an abandoned Redis queue because it saw the code files but not the team's decision to discontinue Redis due to replication lag. That decision "lived in a Slack thread, a couple of PR comments, and the heads of three engineers — places code search cannot reach." The agent did not write bad code. It wrote reasonable code from incomplete context. That is an infrastructure failure, not a model failure.

---

## What They Treat as Load-Bearing

**Traceability must live in the same version-control system as code.** The CLI blog: "Everything Entire records — transcripts, prompts, attribution, summaries — is stored as git objects. Your session history is code, so it should be stored and versioned exactly like code." Their rationale is that anything stored elsewhere drifts. Drift is not a discipline problem — it is the natural state of documentation in a separate system.

They enforce co-location architecturally. Checkpoint metadata travels with the repository, survives rebases because it is linked by commit trailer not commit hash, and is available to anyone who clones the repo.

**Intent review is a different activity than code review, and must happen before it.** From the intent-review post: "Code review addresses: 'Is this change well-implemented?' Intent review addresses a prior question: 'Is this change well-conceived in light of what the team already decided?'" A diff cannot answer the second question. Reviewing a diff to catch a contradiction with a six-month-old decision fails silently — the reviewer doesn't know what they don't know.

Their bet: intent review requires structured, queryable, co-located decision history. Not prose ADRs in a docs folder. Records that an agent queries automatically before making a change: "show me decisions affecting auth that mention session handling." The search has to be lower-friction than guessing, or it does not happen.

---

## Their Worldview on Engineering Teams

Entire's model: humans have moved from primary producers to orchestrators and governors. "The role of the developer is shifting from writing code to conducting an orchestra of agents." (https://entire.io/vision) This is their operating premise, not a forecast. They built Checkpoints for the world where an engineer reviews what agents built.

When an agent generates 90% of a feature, the relevant signal for the next person to touch that code is not the diff — it is the prompt, the alternatives discarded, the session transcript. From the CLI blog: "The author gets better feedback, reviewers know where to focus, and the next person to touch that code knows what they're walking into."

Their internal process reflects this: "Specs focus on context and intent" not exhaustive specification. The spec is a compressed intent artifact, not a contract. If you believe traceability of intent is the core engineering problem, then your own process must produce intent-rich artifacts.

---

## Where This Differs From decree's Current Shape

decree manages the document lifecycle — creation, status transitions, cross-reference integrity, checkbox progress. It enforces that documents are internally consistent and correctly linked to each other.

The gap entire.io's worldview exposes: **decree manages the documents but not the provenance of decisions recorded in those documents.** An ADR in decree is a file with validated frontmatter and a status. What it cannot answer: what alternatives were rejected? What commit introduced the behavior it governs? What changed in the codebase that made this ADR stale before its status was updated? There is no link between the ADR and the code history it describes.

Three pressure points:

**Decisions must be queryable, not just readable.** The intent-review post: "Agents need to query specifically — rather than parsing narrative prose." Decree's frontmatter fields (status, deciders, tags) are a start. The question is whether the schema supports structured pre-change queries, and whether `decree index` produces an artifact an agent can consume programmatically.

**Co-location in git is the only reliable anchor.** Decree already stores documents in git — correct. But the link between a SPEC and the commits that implement it is narrative (a prose reference in the document body) not structural. Entire would say that link should be a git trailer — something that survives rebase, something `git log` can surface.

**Traceability is not a documentation problem — it is an infrastructure problem.** Decree enforces that documents are well-formed and cross-referenced. That is necessary but not sufficient. When a SPEC is marked implemented, what commit did that? When an ADR is superseded, what code change triggered the realization? Decree has no answer because it does not observe the codebase — it only manages the document tree.

---

## What decree Could Adopt From This Worldview

**Treat the gap between document status and code reality as the primary linting target.** Right now decree lints for internal consistency. The more valuable lint would be structural staleness: a SPEC marked `implemented` with no commit trailer linking to it; an ADR `accepted` with no SPEC referencing it within a configurable window. The question decree currently asks is "is this document valid?" Entire would ask "is this document still true?"

**Make the index machine-queryable by design.** `decree index` should be thought of as an agent-facing artifact, not a human-facing summary. That does not require a new database — it requires that the format be specified with an agent consumer in mind.

---

## The Single Most Transferable Principle

Entire's deepest premise: **the "why" has the same lifecycle as the code it explains, and must be stored in the same provenance graph.**

Decree stores documents in the same repository as code. That is the right location but the wrong coupling. The documents need to be connected to code history by something git can traverse — not just by something a human can read. Without that coupling, decree's output is useful to a human browsing a docs folder. With it, decree's output is useful to an agent about to modify the codebase.

That shift does not require adopting Entire's architecture. It requires adopting their framing: traceability is infrastructure, not documentation.
