# Shared State Policy

Date: 2026-05-17

This project is used from both Windows and Mac. The sharing rule is based on file purpose, not on which machine produced the file.

## Principles

1. Machine-specific configuration, private permissions, local paths, local telemetry, caches, and runtime preferences stay local.
2. Project consensus, collaboration rules, reproducible run reports, progress state, and final outputs that the other side must understand or continue should be committed.
3. Both Windows and Mac users follow the same rule set.

## Commit

Commit these when relevant:

- Source code: `*.py`
- Dependency and repo config: `requirements.txt`, `.gitignore`, `.gitattributes`
- Collaboration docs: `AGENTS.md`, `CLAUDE.md`, `COLLABORATION.md`, `docs/*.md`
- Git hooks and shared tool definitions: `githooks/**`, `.claude/settings.json`, `.claude/rules/**`, `.wolf/OPENWOLF.md`, `.wolf/config.json`, `.wolf/hooks/**`
- Project memory and consensus: `.wolf/anatomy.md`, `.wolf/cerebrum.md`, `.wolf/memory.md`, `.wolf/buglog.json`
- Run progress and final outputs: `.progress.json`, `Markdowns/*.md`, `runs/*.md`

## Do Not Commit

Keep these local:

- Videos and extracted media: `Videos/**`
- Local preprocessing cache: `cache/**`
- Python/cache artifacts: `__pycache__/**`, `*.pyc`
- Raw logs: `*.log`
- GitNexus local index: `.gitnexus/**`
- Graphify generated graph/index files: `graphify-out/**`
- OpenWolf local telemetry/state:
  - `.wolf/hooks/_session.json`
  - `.wolf/token-ledger.json`
  - `.wolf/cron-state.json`
  - `.wolf/designqc-report.json`
  - `.wolf/suggestions.json`
- Claude local-only settings such as `.claude/settings.local.json`
- Secrets or credentials in any form, including API keys, cookies, bearer tokens, signed media URLs, and local `.env` files.

## Logs

Use `runs/*.md` for shared run reports and handoff summaries. Raw `zhihuTTS.log` stays local by default because it contains long tracebacks and machine-specific paths. If exact evidence is needed, copy the relevant excerpt into a dated `runs/*.md` report and redact secrets first.

## Commit Shape

Keep commits focused:

- Code changes should not be mixed with run outputs unless the commit is an explicit integration/handoff commit.
- Run-output commits should normally contain only `.progress.json`, `Markdowns/*.md`, and `runs/*.md`.
- Tool-state or memory commits should explain why the other machine needs that context.

If a pre-commit check blocks a legitimate exception, use:

```bash
SKIP_ROLE_CHECK=1 git commit ...
```

and mention the reason in the commit message.
