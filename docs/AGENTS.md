# docs/AGENTS.md

Applies to public documentation under `docs/`.

## Documentation Model

- Keep docs progressive-disclosure: start broad, link to details.
- `docs/index.md` is the capability entry point.
- `docs/usage.md` is command-by-command usage.
- `docs/configuration.md` is the `decree.toml` schema reference.
- `docs/llm-agent-integration.md` is the agent contract.
- `docs/release.md` is release, changelog, and versioning policy.
- `docs/architecture.md` is implementation architecture.

## Style

- Prefer concrete commands over prose-only guidance.
- State explicit failure modes and responsibilities.
- Do not describe silent fallbacks; decree should not have them.
- Avoid duplicating long explanations across docs. Link to the owning doc.
- Keep examples current with canonical `TYPE-ULID` IDs.

## Link Checks

Markdown links are checked online with lychee:

```bash
lychee --config .lychee.toml --no-progress '**/*.md'
```

If you add external links, expect CI to validate them. Do not set lychee
offline mode to hide failures.

## Generated Diagrams

- `docs/model.dot` and `docs/model.png` are generated model artifacts.
- Regenerate them only when the model diagram generator changes.
- Do not hand-edit generated diagrams to make tests pass.

## Changelog

Docs-only user-visible changes still need a `.doc` fragment:

```bash
uv run towncrier create +.doc --content "Document the agent onboarding workflow."
```
