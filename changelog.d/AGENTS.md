# changelog.d/AGENTS.md

Applies to Towncrier fragments in `changelog.d/`.

## Rule

Every user-visible change needs one concise fragment. Do not edit
`CHANGELOG.md` directly during normal development.

## Create a Fragment

No issue number:

```bash
uv run towncrier create +.feature --content "Add governed lookup for auth files."
```

With issue number:

```bash
uv run towncrier create 123.bugfix --content "Fix stale index verification on renamed documents."
```

## Types

- `.security`: security fix.
- `.breaking`: breaking API, schema, or CLI behavior.
- `.feature`: new user-facing capability.
- `.bugfix`: user-visible fix.
- `.doc`: documentation-only change.
- `.deprecation`: deprecated or removed behavior.
- `.dependency`: dependency change.
- `.misc`: internal traceable change.

## Preview

```bash
uv run towncrier build --draft --version X.Y.Z
```

## Fragment Style

- One sentence.
- User-facing.
- Present tense.
- No implementation-only noise unless `.misc`.
- Mention command names and public behavior when relevant.
