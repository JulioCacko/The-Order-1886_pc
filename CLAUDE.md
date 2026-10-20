## Agent skills

### Issue tracker

GitHub Issues on `JulioCacko/The-Order-1886_pc` (`origin`); always pass `-R JulioCacko/The-Order-1886_pc` to `gh`. See `docs/agents/issue-tracker.md`.

### Triage labels

Canonical roles mapped to this repo's labels (`needs-info` -> `question`, `ready-for-agent` -> `ready-to-implement`, others 1:1). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` plus `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## main is protected

Nothing is committed to `main` directly. Land changes through a branch and a pull request; a GitHub
ruleset enforces it on the server, and `scripts/git-hooks/pre-push` refuses it in the checkout once
you enable it:

```sh
git config core.hooksPath scripts/git-hooks
```

That rule is not ceremony: `main` twice took a direct commit here by accident, and each time it was
briefly ahead of anything that had been reviewed.