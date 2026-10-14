# ozgb-skills

Agent skills in the [Agent Skills](https://agentskills.io) format: one
directory per skill under `skills/`, each with a `SKILL.md`. Works with Claude
Code, opencode, Codex and any other agent that `npx skills` supports.

```bash
npx skills add ozgb/ozgb-skills                          # pick interactively
npx skills add ozgb/ozgb-skills --skill comment-cleanup
```

| Skill | What it does |
|-------|--------------|
| [comment-cleanup](skills/comment-cleanup/SKILL.md) | Comment-only pass: delete narration and noise, keep comments that carry *why* |
