# skills/AGENTS.md

Applies to portable agent skills under `skills/`.

## Rules

- Keep each skill self-contained in a folder with a required `SKILL.md`.
- Keep `SKILL.md` concise; link to public docs for deeper context instead of
  duplicating long explanations.
- Skills may call LLM runtimes, but core decree must not gain provider
  dependencies or hidden fallbacks through a skill change.
- Skills must use public CLI contracts where possible. Prefer `--json` inputs
  and explicit preview/apply commands.
- If a skill writes files, it must state the exact command or schema that
  validates those files before any apply step.
