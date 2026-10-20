# Changelog

Maintain a concise, factual record for changes on the active feature branch. Link to the exact commit/acceptance report, distinguish mock/replay vs live tests, and list known limits. Do not describe unverified behavior as complete.

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
