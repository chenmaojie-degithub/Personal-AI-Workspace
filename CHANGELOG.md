# Changelog

Maintain a concise, factual record for changes on the active feature branch. Link to the exact commit/acceptance report, distinguish mock/replay vs live tests, and list known limits. Do not describe unverified behavior as complete.

## 2026-10-20 — Live Citation check and PostgreSQL backup readiness

- Docs-only validation update; no runtime code or configuration changes. Synced `AGENTS.md` / existing history safely from `origin/feat/agent-core` before validation.
- **Live model:** one explicitly approved streaming inference on `nvidia/nemotron-3-super-120b-a12b:free` passed the current citation-marker protocol, mixed Web/knowledge numbering, duplicate-URL deduplication and streaming/synchronous equivalence. Reused saved Exa URL; no new Exa calls.
- **Actual usage:** 365 input + 209 output = 574 tokens; API-reported cost $0; first visible text 4.312s, total 6.219s. One public model-catalog GET verified the listed zero input/output pricing and tools support. No retries or model switching. This is one final-answer check, not full live Agent end-to-end sign-off.
- **PostgreSQL:** existing `sources_json` column verified read-only; consistent custom-format backup created outside Git and archive listing validated. Isolated restore database creation failed with `InsufficientPrivilege` (`CREATEDB` unavailable); database writes stopped. Original messages/Sources/Workspaces were not modified. Full restore, legacy-column migration and PostgreSQL persistence acceptance remain **BLOCKED**, not passed.
- **Tests:** targeted offline Citation/Persistence regression: **19 passed, 59 subtests passed**. No local full rebuild for these documentation-only changes; prior full CI results remain historical evidence.
- Report: `docs/acceptance/citation-live-postgres-2026-10-20.md`. Next: have an administrator provision a separate restoration database, then verify migration/recovery on that copy without expanding production-account privileges.

## 2026-10-20 — Citation identity and streaming reliability

- **`04624ed` — `fix(citations): bind streamed answers to stable persisted sources`**
  - Backend citation registry deduplicates sources and assigns stable `citation_id`; the final-answer stream validates markers and only emits mapped `【n】` citations.
  - Invalid/unknown citations fail explicitly without persisting an invalid answer; messages and source metadata persist together for refresh/reload.
  - Updated Agent orchestration, chat routes, model/database structures, frontend Sources UI, regression tests and acceptance/replay artifacts.
  - Reported verification: backend **136 passed, 65 subtests passed**; frontend typecheck/build passed; **6/6** HTTP SSE replay scenarios; browser replay Sources, clickable links and reload passed; CI passed.
  - **Not yet verified:** live LLM adherence to marker protocol; migration against the user's actual PostgreSQL data. These results are not a full live-provider end-to-end sign-off.
  - Report: `docs/acceptance/citation-acceptance-2026-10-20.md`.

## 2026-10-14 — Offline test isolation

- **`7a8e8fc` — `test: isolate provider traffic and guard loopback proxy escapes`**
  - Extended test isolation and added coverage for proxy escape and DDGS patch location.
  - This is an application-level test safeguard, **not** a general network sandbox.
  - Report: `docs/acceptance/network-isolation-2026-10-14.md`.

## 2026-10-12 — Exa web-search provider

- **`f14e83e` — `feat(search): add Exa provider with explicit DDGS fallback selection`**
  - `SearchProvider` abstraction; Exa default (`auto`, up to 5 results, highlights), DDGS optional via explicit config; existing `search_web` and Citation flow preserved.
  - Initial live Exa verification: 3 deliberate search requests succeeded (HTTP 200). An earlier test-isolation gap could have triggered additional Exa calls; exact historical usage is unconfirmed.
