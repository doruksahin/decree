# Release, Changelog, and Versioning

Decree uses static package metadata as the version source of truth.
Changelog entries are managed with Towncrier fragments.

## Source of Truth

The canonical package version is:

```toml
[project]
version = "3.0.0"
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

Tag-derived versions would add moving parts without providing a stronger source
of truth because release tags are created after `pyproject.toml`,
`CHANGELOG.md`, and validation are already complete. The current rule is
simpler:

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

6. Commit the release-preparation changes.

   ```bash
   uv run decree commit -m "chore: prepare vX.Y.Z release" --no-infer
   ```

7. Verify the exposed version.

   ```bash
   uv run decree --version
   ```

8. Run validation.

   ```bash
   uv run pytest -q
   uv run pre-commit run --all-files
   ```

9. Build artifacts locally if you want a pre-tag smoke test.

   ```bash
   uv build
   ```

10. Tag the release after validation.

   ```bash
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```

11. GitHub Actions runs `.github/workflows/release.yml`.

    The workflow validates the release, builds the source distribution and
    wheel, creates a GitHub Release with both artifacts, and bumps the Homebrew
    tap to the new version. decree is not published to PyPI (see Distribution).

## Release Workflow

The release workflow is tag-triggered:

```yaml
on:
  push:
    tags:
      - "v*.*.*"
```

It fails closed unless all release readiness checks pass:

- tag must be `vX.Y.Z`
- tag version must equal `[project].version`
- `CHANGELOG.md` must contain a `## vX.Y.Z` release section
- `changelog.d/` must have no pending release fragments other than
  `README.md` and `AGENTS.md`
- ruff, format check, decree lint, index verify, tests, and lychee must pass

Workflow YAML is statically validated by `actionlint` in both pre-commit and
pull request CI. Do not add or change a workflow without that check passing.

## Distribution

decree is **not** published to PyPI: the name `decree` there belongs to an
unrelated third-party project, and it cannot be claimed while that project is
active ([PEP 541](https://peps.python.org/pep-0541/) only reassigns abandoned
names). Releases are distributed two ways instead:

- **GitHub Release** — the `github-release` job attaches the wheel and sdist to
  the `vX.Y.Z` release. Install with
  `uv tool install git+https://github.com/doruksahin/decree`, from a release
  asset directly, or with pip via
  `pip install "decree @ git+https://github.com/doruksahin/decree"`.
- **Homebrew** — the `homebrew` job rewrites the formula in the
  [`doruksahin/homebrew-decree`](https://github.com/doruksahin/homebrew-decree)
  tap to the new release sdist and pushes it, so
  `brew install doruksahin/decree/decree` tracks the latest version.

### Homebrew tap — first-time setup

Before the first release, in this order:

1. Create the `doruksahin/homebrew-decree` repository and push the tap contents
   (`Formula/decree.rb`, `README.md`). The formula ships with placeholder
   `url`/`sha256` until the first release fills them.
2. Add a repository secret `HOMEBREW_TAP_TOKEN` to the **decree** repo: a
   fine-grained personal access token scoped to `homebrew-decree` with
   **Contents: write**.
3. Cut the first `vX.Y.Z` release. The `homebrew` job rewrites the formula to the
   release sdist and pushes it.

Without steps 1–2 the `homebrew` job fails at checkout (loudly) rather than
shipping a stale formula.
