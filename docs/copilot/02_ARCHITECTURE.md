> **v1.3 authoritative override:** React + TypeScript + Vite + Tailwind + WaveSurfer.js frontend; FastAPI backend; docs live in `docs/copilot/`. Any earlier Streamlit or Python-only UI guidance in this document is superseded by `15_FRONTEND_ARCHITECTURE.md`, `16_UI_UX_SPECIFICATION.md`, and `17_UI_WIREFRAMES.md`. Do not implement Streamlit.

# Architecture and boundaries

## Design
`manifest + optional overrides -> validation/probe -> resolved project model -> shared timeline -> preview/render services -> verification + publishing metadata`.

**Backend:** Python 3.11+ domain/application services, JSON Schema/Pydantic validation where approved, filesystem adapters, and FFmpeg/FFprobe infrastructure. **UI:** React + TypeScript + Vite + Tailwind; WaveSurfer.js Regions for waveform interaction. FastAPI is a thin local adapter. Do not implement Streamlit or a second rendering engine in JavaScript.

## Package direction
```
backend/src/wrld_video_studio/
  domain/                  # pure versioned models and invariants
  application/             # use cases and ports
  infrastructure/          # FFmpeg/FFprobe/filesystem adapters
  interfaces/http/         # thin local FastAPI adapter
  interfaces/cli/          # headless adapters, beginning with WU3A export
frontend/                  # future WU4+ React application
contracts/schemas/         # approved machine contracts
backend/tests/             # unit, contract, integration
```

WU3A adds separate product album/track render planning and encoding behind ports. It reuses the existing WU2 job repository, process ownership, artifact lifecycle and WU3 shared admission. It must not relax the synthetic-proof encoder or let a CLI construct an independent FFmpeg pipeline.

The caller supplies the album-project directory at runtime. That directory—not the music-library root or source repository—is the source-resolution and final-artifact boundary. Persist portable paths relative to the project where appropriate; resolve/canonicalize them through the approved secure filesystem adapters and reject traversal, symlink/reparse escape, source/output aliasing, or paths outside the project. Final artifacts live under `<album-project>/output/`. WU3A neither creates nor relocates the primary album directory and must not derive it from the process working directory or repository location.

## Critical contracts
- `Project` has immutable identity/source paths and mutable visual overrides; audio duration and track offsets are **derived** from FFprobe, never trusted from user-entered JSON.
- `Timeline` is computed once and shared across compilation titles, chapters, Short extraction, progress, and reports.
- `Short` references stable track ID, stable short ID, `start_seconds` and `end_seconds` relative to that track. Keep fractional seconds.
- Preview and final render use one resolved visual-settings object and common filter builders. Do not duplicate profile or layout logic.
- Separate *planned settings* from *measured render results*. Reports record command/version, input hashes or size/mtime, duration, codecs, settings, warnings and status.
- Headless application interfaces remain usable without React/Node. UI adapters must call application services, not shell out to a CLI or rewrite media algorithms.
- No global `cwd`, repository-location, drive, username, library-root, channel, or album-name assumptions. Use owned subprocess argument arrays; FFmpeg filter escaping and media paths require Windows tests.

## Compatibility
Legacy v2 manifest uses `album_title`, `background`, `tracks[{title,file,shorts}]`. Provide an adapter so these still work; avoid silently replacing existing album JSON. Existing WRLD-FI canonical JSON nests tracks under `album.tracks` and contains many extra fields. Treat it as read-only external source and introduce a later adapter; do not force its schema into the POC.

## v1.1 orchestration boundary
React/FastAPI and CLI adapters invoke shared application services for validate/preview/save/queue/cancel/export. The local coordinator is the single writer of job state and admits at most one heavy FFmpeg operation; render workers receive immutable job snapshots and emit verified results. FFmpeg operations live behind testable infrastructure adapters. No C#/.NET, Docker, microservices, or distributed queue in this POC. See Docs 10, 11, 21, 34, 37, and 38.

## v1.2 architecture rule
Use a ports-and-adapters layout: domain and application use cases must not depend on React, FastAPI, FFmpeg implementations, filesystem implementations, or Music Analyzer code. CLI, HTTP, and UI adapters invoke the same use cases. See `14_MICROSERVICE_READY_ARCHITECTURE.md` for dependency direction and package layout.
