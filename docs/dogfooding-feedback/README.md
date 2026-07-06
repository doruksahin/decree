# Decree Dogfooding Feedback

This pack captures concrete feedback from using decree in live Agentkith
development. It is not a feature spec yet. Its job is to separate observed
friction from proposed fixes so decree can become more useful without making
governance heavier.

Use this pack when changing decree commands, public docs, or agent skills based
on real workflow pain.

## Read Order

1. [Executive summary](00-executive-summary.md)
2. [Agentkith evidence](01-agentkith-evidence.md)
3. [Pain points](02-pain-points.md)
4. [Command improvements](03-command-improvements.md)
5. [Skill and usage improvements](04-skill-and-usage-improvements.md)
6. [Controlled rollout plan](05-controlled-rollout-plan.md)

## Scope

This pack focuses on the development loop around:

- `decree why`
- `decree refs`
- `decree intent-check`
- `decree progress`
- `governs:` maintenance
- agent skills that tell LLM sessions how to use decree

It does not replace the existing command reference in
[usage.md](../usage.md), the agent contract in
[llm-agent-integration.md](../llm-agent-integration.md), or the drift model in
[health-signals.md](../health-signals.md).

