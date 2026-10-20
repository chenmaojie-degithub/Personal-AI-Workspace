# AGENTS.md — Personal AI Workspace

Applies to this repository. Work on the current feature branch; do not edit, merge, or force-push `main` without explicit approval.

## Default execution rules
- Respond in concise Chinese. Start with the requested goal, affected files, and minimum viable change. Avoid unnecessary planning, full-repo scanning, speculative refactors, and long terminal output.
- **Minimize Codex token/credit consumption:** inspect `git status`, relevant diffs and specific files first. Use targeted search/line ranges rather than dumping entire files; reuse already-obtained context. Make the smallest correct patch in one pass, with a bounded debugging loop. Do not repeatedly run the same tests without code changes or a reason.
- Prefer deterministic offline mocks for Exa, DeepSeek, OpenRouter, Embedding and Agent tests. Never allow tests to use real credentials or perform unapproved external API calls. Network protections are best-effort test controls, not a full OS sandbox.
- Verify incrementally: targeted tests for affected behavior, then full backend/frontend checks when behavior changes or before delivery. A docs-only edit may use diff/format checks without expensive builds; rely on existing CI for GitHub verification.
- Never print secrets, read out API-key values, add `.env` files, or disclose personal data in reports. Avoid replacing user data or rewriting migrations casually.
- Preserve unrelated uncommitted changes; no destructive reset/clean. No force push. Stop and report a concrete blocker when checks fail rather than claiming success.
- For each completed, verified change: summarize scope, motivation, files, tests, limitations, and costs; update `CHANGELOG.md` with accurate facts, commit a small scoped change, push to the existing feature branch and update the existing PR description. Never merge the PR or touch `main` without explicit approval.
- Before committing/pushing, inspect `git diff --check`, staged diff, sensitive files and branch/remote state. Never commit unknown or unverified changes. If push/CI fails, report and stop.
- Distinguish: mocks vs real API; replay browser vs real provider; local tests vs CI; proposed vs executed. No invented evidence.
- Real Exa/LLM requests, paid model switching, additional purchases, and external actions require explicit per-run authorization and a small call/token budget. No automatic retries unless approved.

## Current known state (2026-10-20)
- Branch: `feat/agent-core`; Agent core, web/RAG search, Exa provider, citation registry, SSE validation and citation persistence are implemented.
- Citation/HTTP/browser replay tests passed; real LLM compliance with the citation-marker protocol and migration on the user's PostgreSQL database remain unverified.
- Continue with the smallest validation of these remaining gaps, then Agent observability (tool/model trace, TTFT, latency, token/cost, failure categories). Do not expand scope automatically.
