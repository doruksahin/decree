# Changelog Fragments

Every user-visible change must add one Towncrier fragment in this directory.

Use orphan fragments when there is no issue number:

```bash
uv run towncrier create +.feature --content "Add scoped progress for parallel agent work."
```

Use issue-linked fragments when a GitHub issue exists:

```bash
uv run towncrier create 123.bugfix --content "Fix stale index verification on renamed documents."
```

Fragment types:

- `.security` for security fixes.
- `.breaking` for breaking API/CLI behavior.
- `.feature` for new user-facing capability.
- `.bugfix` for user-visible fixes.
- `.doc` for documentation-only changes.
- `.deprecation` for deprecated or removed behavior.
- `.dependency` for dependency changes.
- `.misc` for internal changes that should still be traceable.

LLM agents should prefer one concise, user-facing sentence per fragment. Do not
edit `CHANGELOG.md` directly except during `towncrier build` release flow.
