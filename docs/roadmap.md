# Roadmap

Feature ideas and open questions for decree. Items here are not committed — they're candidates for future PRDs.

## Planned (has PRD)

### DDD CLI Command & Proofshot Integration

[PRD-002](../decree/prd/002-ddd-cli-command-and-proofshot-integration.md) — approved, needs ADRs.

- `decree ddd` — phase detection from the terminal, no Claude Code required
- Completion reports — auditable proof when a SPEC reaches 100%
- Claude Code stop hook — capture project state between sessions

## Ideas

### Lightweight Decision Log

**The question:** Decree tracks heavyweight decisions (PRD → ADR → SPEC). But teams also make dozens of smaller decisions — "use ruff for linting", "ship a skill template", "pin Python 3.11+". These don't warrant a 3-document chain. Where do they go?

**Industry terms:**

- **LADR** (Lightweight Architecture Decision Record) — [coined by ThoughtWorks](https://www.thoughtworks.com/radar/techniques/lightweight-architecture-decision-records). A simplified ADR with just context, decision, and consequences. No options analysis, no deep rationale.
- **Any Decision Record** — [proposed by Olaf Zimmermann](https://ozimmer.ch/practices/2021/04/23/AnyDecisionRecords.html). Extends ADR beyond architecture to design, process, and organizational decisions. MADR itself was renamed from "Markdown Architectural Decision Records" to "Markdown **Any** Decision Records" to reflect this.
- **Decision Log** — [Microsoft's term](https://microsoft.github.io/code-with-engineering-playbook/design/design-reviews/decision-log/). The aggregate collection of all decisions, not a separate format. In decree terms, this is just `decree index` output.
- **Y-Statement** — a [one-sentence decision format](https://medium.com/olzzio/y-statements-10eb07b5a177): "In the context of [situation], facing [concern], we decided for [option] to achieve [quality], accepting [downside]."

**What it could look like in decree:**

```toml
[types.decision]
dir = "decree/decisions"
prefix = "DEC"
digits = 3
initial_status = "proposed"
statuses = ["proposed", "accepted", "rejected"]
warn_on_reference = ["rejected"]
required_sections = ["Context", "Decision"]
```

**Open questions:**

- Is this just a simpler ADR type that users can already define in `decree.toml` today? (Answer: mostly yes — decree is config-driven, you can define any type)
- Should decree ship a built-in LADR template, or let users create their own?
- Does a lightweight type need a simpler lifecycle? (proposed → accepted, skip review?)
- How does [Spotify decide](https://engineering.atspotify.com/2020/04/when-should-i-write-an-architecture-decision-record) what's "significant enough" for an ADR vs a lightweight record? Should decree have guidance on this?

### Release Notes Skill

**The question:** When a SPEC reaches "implemented", the decision chain (PRD → ADR → SPEC) already tells the story of what changed and why. Could a Claude Code skill read this chain and help draft release notes?

**What it would do:**

- Run `decree progress` to find implemented SPECs since last release
- Walk the reference chain to gather context (PRD motivation, ADR rationale)
- Help draft a changelog entry in [Keep a Changelog](https://keepachangelog.com) format
- Leave actual version bumping to the user's existing tooling

**What it would NOT do:**

- No `decree release` CLI command (versioning is a different domain)
- No `bump:` field in frontmatter (pollutes decision records with release concerns)
- No git tag management, no PyPI publishing

**Why not build it into core:** [Top Python projects](https://docs.astral.sh/ruff/versioning/) (ruff, uv, Pydantic, FastAPI) all handle versioning manually. Semver is about API contracts with consumers; ADRs are about internal reasoning. Different granularity, different audience. A skill composes with decree without bloating it.

### Custom Templates per Type

**The question:** Decree ships 3 built-in templates (PRD, ADR/MADR v4, SPEC). Users can set `template = "path"` in config. But there's no `decree template` command to scaffold or list available templates.

**Open questions:**

- Is `decree template list` useful, or is `ls src/decree/templates/` sufficient?
- Should users be able to override built-in templates without forking?
- Template inheritance — should a custom template extend the built-in one?
