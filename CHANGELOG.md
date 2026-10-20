# Changelog

Maintain a concise, factual record for changes on the active feature branch. Link to the exact commit/acceptance report, distinguish mock/replay vs live tests, and list known limits. Do not describe unverified behavior as complete.

## 2026-10-20 — Long-term Memory V1

- Added opt-in `MemoryService` and explicit Workspace-scoped CRUD/query APIs using a separate SQLite sidecar, never the business database connection. User confirmation is mandatory for create/update; normalized keys deduplicate identical writes, conflicting creates/stale updates or deletes return 409. Every lookup/mutation includes Workspace scope. No automatic extraction, memory write tools, frontend manager, embeddings or Chroma changes.
- Ordinary Chat and Agent, synchronous and SSE, reuse bounded lexical memory context across Sessions. At most 3 matching records, deterministic ordering, full serialized-message UTF-8 byte cap plus framing reserve (default 512, hard maximum 2048). This is a conservative byte-level tokenizer bound, not measured usage for arbitrary providers. Memory values remain JSON user-context data; only a fixed server policy is system-level. Storage failure skips injection without logging private contents.
- Added 22 offline tests: CRUD/confirmation, duplicate/conflict/version checks, Workspace boundaries, deletion, cross-session injection across four paths, Chinese matching, budget, hostile-content structure, disabled/no-DB path, wrong-file refusal, independent storage with business connections forbidden, and SQLite backup/restore integrity. Targeted **22 passed**; full backend **187 passed**; `vue-tsc --noEmit` and production build passed, existing warnings only.
- Default remains disabled; no `.env` modification, user PostgreSQL connection/DDL/migration or real LLM/Exa/Embedding requests. PostgreSQL production migration and live-model acceptance remain **NOT VERIFIED**. Docs include schema, API examples, migration/rollback design and limits: `docs/memory-v1.md`. Sidecar orphan retention after Workspace deletion and in-flight context snapshots are explicitly documented; no automatic user-data deletion.

## 2026-10-20 — Agent Evaluation V1

- Added 12 fixed offline scenarios using existing Mock Provider helpers, real routing/Agent execution, server tool validation, Citation registry and temporary SQLite persistence. Covers direct answers, Web, RAG, mixed evidence, failure recovery, malformed calls, citation identity/deduplication, invalid citations, token limits, cancellation and Workspace boundaries. No application runtime changes, real API requests or user PostgreSQL access.
- Added independent expected tool/source identities, deterministic scoring and explicit JSON export with source hashes. Baseline: **12/12 scenarios passed**, **12/12 tool sequences matched**, **0 forbidden executions**, **8/8 emitted references valid**; records 2 rejected dispatch attempts, 1 intentionally repeated search and 44 Mock model calls. Four unknown Usage scenarios keep aggregate Usage null; known subtotal is 272 synthetic tokens, not a bill or complete usage total.
- Targeted suite **15 passed** (12 scenarios + 3 scorer safeguards); full backend **165 passed**; `npx vue-tsc --noEmit` and `npm run build` passed. Existing Starlette deprecation and Vite bundle-size warnings remain.
- Fixed-script pass rate does not establish live model task success or factual accuracy. RAG/search handlers are synthetic; SSE is exercised through its route generator, not a new browser/HTTP acceptance run. Original PostgreSQL recovery blocker remains unchanged. Report/reproduction: `docs/agent-evaluation-v1.md`; machine baseline: `docs/evaluation/agent-evaluation-v1.json`.

## 2026-10-20 — Agent Observability V1

- Added bounded per-run monotonic measurements for total duration, first nonblank Citation-validated text (TTFT), individual tool spans, Provider call attempts/durations/Usage, and terminal stage/error type. Reuses Agent orchestration and budgets; no new monitoring framework or external API calls.
- Persists optional versioned metrics in existing `agent_runs.plan_json` metadata; old plan arrays remain readable and public `plan` stays an array. No new columns, DDL or backfill; did not connect to or modify the user's PostgreSQL. New-envelope rollback compatibility must be checked on an isolated copy before deployment.
- Added `agent_metrics` SSE snapshots and metrics projection through existing run detail APIs; original Agent panel now displays timing, model/tool attempts, nullable usage/cost, and errors. Unknown or incomplete Usage stays null, including unreported failed attempts before repair; fees are never guessed as zero.
- Offline tests cover completion, recovered tool failure, LLM failures, cancellation before/after Usage arrives, token-budget termination, missing Usage, repair attempts, Citation-buffer TTFT, disconnect, legacy persistence and SSE/detail Workspace consistency. New suite **14 passed**; complete backend **150 passed, 65 subtests passed**; `vue-tsc --noEmit` and frontend build passed (existing warnings only).
- Limitations: Provider count is not SDK HTTP retry count; stream timing includes consumer/backpressure waiting; no fresh browser/live-provider acceptance or PostgreSQL recovery sign-off. Original simple Chat remains on its existing path. Docs: `docs/agent-observability-v1.md`; technical handbook updated.

## 2026-10-20 — Project architecture and learning handbook

- Added `docs/technical-handbook.md`: a detailed Chinese handbook with 32 consistently structured topics covering the actual frontend/backend stack, model/providers, Agent/tools, SSE, RAG/search/citations, persistence, data analysis, long-term memory, security, evaluation, observability and future deployment/model topics.
- Each topic explains concepts, mechanisms, current code, the problem solved, examples/validation, limitations, future study and interview questions. Clearly distinguishes the custom orchestrator from LangChain/LangGraph, implemented behavior from future directions, and live-provider evidence from mock/replay results.
- Verified against dependency manifests and relevant source; added an architecture/data-flow diagram, code links, terminology comparisons, learning exercises and primary documentation references. Long-term memory receives its own treatment rather than replacing the rest of the handbook.
- Docs-only change: checked all 32 topic structures, local links, code-fence balance, anchors, sensitive patterns and Git diff. No backend/frontend runtime changes or repeat full local build; no Exa, Embedding or LLM inference requests. Existing PostgreSQL restore permission blocker remains unchanged.

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
