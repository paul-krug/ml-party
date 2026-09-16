# Contributing

Thanks for looking. ml-party is early (0.x) and small; issues and focused
pull requests are both welcome.

## Before a big change, open an issue

For anything beyond a bug fix or a doc correction, open an issue first so
the design can be agreed before you spend the effort. Planning lives in the
repo's GitHub Project, so an issue is also how work gets scheduled.

## The flow

```bash
git clone https://github.com/paul-krug/ml-party && cd ml-party
python -m venv .venv && .venv/bin/pip install -e .
(cd ui && npm install && npm run build)       # web UI bundle, once
```

Then:

1. Branch off `main` (`feat/…`, `fix/…`, `docs/…`).
2. Keep the PR **single-purpose and small**. Large mixed PRs are hard to
   review and get split before review.
3. Make the gates pass locally — the same eight run in CI:
   ```bash
   .venv/bin/python -m pytest tests/ -q
   .venv/bin/ruff check src tests scripts
   .venv/bin/python -m sphinx -b html docs docs/_build
   ```
4. Run the **[doc-sync](.agents/skills/doc-sync/SKILL.md)** pass — audit
   which docs your change touches and update them in the same PR. "No doc
   impact" is a valid, recordable result.
5. Open the PR. `main` is protected: every check must pass and the branch
   must be current with `main` before it can merge.

Conventions (commit prefixes, store invariants, test helpers, known
gotchas) live in [AGENTS.md](AGENTS.md) — worth reading once whether you
are a human or an agent.

## Agent-instruction files are maintainer-only

**PRs from outside contributors that touch these paths are closed
automatically:**

- `AGENTS.md`, `CLAUDE.md`
- anything under `.agents/` (skills an agent executes)
- any `SKILL.md`
- anything under `.github/` (the CI gates, CODEOWNERS, and the release
  workflow that publishes to PyPI)

This is not about the quality of your change. These files are read by AI
coding agents as **instructions**, so a merged edit can direct a
maintainer's agent on their own machine — a prompt-injection payload that
never needs to run in CI to do harm. The reasoning is spelled out in
[SECURITY.md](SECURITY.md#threat-model-the-agent-instruction-supply-chain).

If you think one of these files should change — and sometimes it should —
**open an issue** describing the change and why. A maintainer will carry
it in. Changes to `src/mlparty/mcp_server.py` are not auto-closed, since
real feature work lands there, but its instruction text ships to every
user's agent, so expect close review of any wording change.

## Reporting a vulnerability

Do not open a public issue — use GitHub's **"Report a vulnerability"**
(Security tab). See [SECURITY.md](SECURITY.md).
