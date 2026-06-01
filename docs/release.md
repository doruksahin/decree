# Release, Changelog, and Versioning

Decree uses static package metadata as the version source of truth.
Changelog entries are managed with Towncrier fragments.

## Source of Truth

The canonical package version is:

```toml
[project]
version = "0.1.0"
```

in [`pyproject.toml`](../pyproject.toml).

Runtime version surfaces read the installed package metadata:

- `decree.__version__`
- `decree --version`
- `importlib.metadata.version("decree")`

Do not hardcode the same version in multiple source files. Tests verify that
runtime metadata, CLI output, and `pyproject.toml` stay synchronized.

## Changelog Source of Truth

Pending changelog entries live in `changelog.d/` as Towncrier fragments.
`CHANGELOG.md` is release output. Do not manually edit `CHANGELOG.md` for
normal feature work.

Every user-visible change should include exactly one concise fragment unless it
is a pure release operation.

Use an orphan fragment when there is no GitHub issue:

```bash
uv run towncrier create +.feature --content "Add scoped progress for parallel agent work."
```

Use an issue-linked fragment when one exists:

```bash
uv run towncrier create 123.bugfix --content "Fix stale index verification on renamed documents."
```

Fragment types:

| Type | Use for |
|------|---------|
| `.security` | Security fixes |
| `.breaking` | Breaking API, schema, or CLI behavior |
| `.feature` | New user-facing capability |
| `.bugfix` | User-visible fixes |
| `.doc` | Documentation-only changes |
| `.deprecation` | Deprecated or removed behavior |
| `.dependency` | Dependency changes |
| `.misc` | Internal traceable changes |

LLM agents must create the fragment as part of the same change they are making.
This is intentional: the release note is written while the context is fresh,
not reconstructed from git history later.

## Why Not Git-Derived Versioning Yet?

Hatch supports dynamic version sources, including VCS-derived versions through
`hatch-vcs`. That is useful once release tags are authoritative.

This repository currently has no release tags or publish workflow, so
tag-derived versions would add moving parts without providing a stronger source
of truth. The current rule is simpler:

- `pyproject.toml` owns package version.
- `CHANGELOG.md` owns human release notes.
- Git tags may be added during release, but they do not compute the package
  version.

Revisit VCS-derived versioning only after releases are consistently tagged and
published from CI.

## Preview Changelog

Before release, preview the generated notes without modifying files:

```bash
uv run towncrier build --draft --version X.Y.Z
```

## Release Checklist

1. Choose the next semantic version.
2. Update `[project].version` in `pyproject.toml`.
3. Run `uv sync`.
4. Preview release notes.

   ```bash
   uv run towncrier build --draft --version X.Y.Z
   ```

5. Build `CHANGELOG.md` from fragments.

   ```bash
   uv run towncrier build --yes --version X.Y.Z
   ```

6. Verify the exposed version.

   ```bash
   uv run decree --version
   ```

7. Run validation.

   ```bash
   uv run pytest -q
   uv run pre-commit run --all-files
   ```

8. Build artifacts.

   ```bash
   uv build
   ```

9. Tag the release after validation.

   ```bash
   git tag vX.Y.Z
   ```

10. Publish artifacts with the repository's chosen publishing workflow.
