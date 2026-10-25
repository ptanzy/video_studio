# 15 — Frontend Architecture (v1.3, authoritative)

## Decisions
- Frontend: React 18+ with TypeScript (strict), Vite, Tailwind CSS; WaveSurfer.js with Regions plugin.
- Backend: FastAPI thin HTTP adapter around Python application services; FFmpeg and FFprobe only in infrastructure layer.
- Frontend unit/component tests: Vitest + React Testing Library. Browser E2E: Playwright. API tests: pytest + httpx TestClient/AsyncClient.
- POC runs on localhost. No authentication or public binding by default. Do not add database, message broker, Docker, or cloud infrastructure merely to implement this POC.
- UI must not shell out to FFmpeg or import Python. Backend use cases must not import React or FastAPI.
- Prefer API-generated low-resolution still/video previews for final fidelity. Frontend CSS tint is a fast *approximation* only, explicitly labeled until refreshed.

## Proposed repository paths
```
frontend/src/app/{App.tsx,routes.tsx}
frontend/src/features/import/{ImportPage.tsx,AlbumSummary.tsx}
frontend/src/features/review/{ReviewPage.tsx,ShortCarousel.tsx,ArtworkPreview.tsx,WaveformSelector.tsx,VisualControls.tsx}
frontend/src/features/render/{RenderPage.tsx,JobProgress.tsx}
frontend/src/api/{client.ts,types.ts}
frontend/src/components/{Button.tsx,Panel.tsx,Status.tsx}
frontend/tests/
backend/src/wrld_video_studio/{domain,application,infrastructure,interfaces/http}
backend/tests/
contracts/schemas/
docs/copilot/
docs/ui/
```

## API contract proposal (validate before implementation)
- `POST /api/v1/albums/validate` — manifest and referenced media validation; never modify source WAVs.
- `GET /api/v1/albums/{album_id}` — resolved album and tracks, with stable recording/track IDs.
- `GET /api/v1/tracks/{track_id}/audio` — stream WAV or supported browser-playable proxy; support seeking/range requests.
- `POST /api/v1/previews/still` — visual configuration + track/short ID -> cached preview reference.
- `POST /api/v1/previews/motion` — request low-res 3–5s preview; return job/ref, not block request.
- `GET/PUT /api/v1/albums/{album_id}/overrides` — versioned overrides with optimistic revision check (409 conflict).
- `POST /api/v1/render-jobs` — immutable config snapshot, idempotency key, queued render job.
- `GET /api/v1/render-jobs/{job_id}` — status/progress/results/errors; polling sufficient for POC.
- `POST /api/v1/render-jobs/{job_id}/cancel` — cancellation request.

All endpoint names and payloads are proposals to finalize in WU0; do not implement contradictory contracts silently. Use generated or hand-maintained typed TS interfaces matching versioned JSON Schemas; add contract tests.

## Dependency and lifecycle rules
WaveSurfer instance is created once per mounted waveform component, disposed on unmount/track change; Regions plugin events update React state. Avoid recreating WaveSurfer on each drag frame. Debounce persistence, explicit Save action, and protect against stale responses. Use stable IDs, not list indexes, in persistent payloads. Handle loading, empty, error, cancellation and conflict states. Keep real audio playback within selected bounds; playback must stop at `end_seconds` and restart at `start_seconds`.

## WU3A dependency note

WU3A precedes frontend implementation and provides headless album/track validation, timeline/chapters, static MP4 export, and the album-project boundary with artifacts under project-local `output/`. WU4 consumes validation/timeline plus the existing WU3 still-preview API for Import/Review and owns the future project initialization/selection UX beneath configurable library roots, including room for selectable locations and multiple channels; it does not add render-job HTTP endpoints. WU6 finalizes the proposed render-job routes/payloads and connects the Render page to the WU3A application use cases. The browser must identify a server-approved project and must never submit an arbitrary local server path. Endpoint examples above remain proposals until their work-unit contract review.


## v1.4 frontend modules
Add `ColorTreatmentEditor` to Review and `MetadataReviewPage`/`VideoMetadataEditor`/`ChapterPreview`/`MetadataValidationPanel` to frontend routes. Typed API clients call versioned FastAPI endpoints; backend owns schema validation, override revisions, and authoritative previews. New controls and metadata must have Vitest/RTL and Playwright coverage (doc 20).
