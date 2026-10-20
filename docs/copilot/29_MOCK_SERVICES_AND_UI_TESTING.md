# 29 — Mock services and UI testing (v1.7 normative)

## One backend contract
React/Vite/TypeScript UI communicates with the thin local FastAPI HTTP adapter. Frontend tests use MSW (Mock Service Worker) or equivalent request interception with contract-conformant fixtures. Backend tests use FastAPI TestClient and injected fake application ports. **Do not create a second Express or JSON-server production backend.** Mock responses must use the same OpenAPI models as the real API; never hand-invent fields that have no contract.

## Test matrix
- Vitest + React Testing Library: validation, editor state, selected IDs, keyboard and accessibility.
- Playwright against React app with mocked HTTP: Import → Review → Metadata → Render; waveform region drag/resize/save/reload; preview compare; batch metadata editing; progress disconnected/reconnected; error and retry UI.
- Playwright smoke for `docs/ui/index.html` separately as a *reference artifact*, not proof of app functionality.
- pytest + FastAPI TestClient: success/error envelopes, request validation, revision conflicts, fake job progress and retries.
- FFmpeg integration (marked separately): real synthetic audio and short videos, duration/frame/color/audio validation; no GPU requirement.

## Test hygiene
Synthetic 1–5 second WAV/video fixtures and deterministic fake clock for progress; no network, Suno, live AI, real YouTube upload or cloud services. Fail tests on console errors, missing interactive labels and stale mock contract fixtures. UI acceptance is blocked if a mocked flow has no corresponding documented real API route or a named deferred route.
