> **v1.3 authoritative override:** React + TypeScript + Vite + Tailwind + WaveSurfer.js frontend; FastAPI backend; docs live in `docs/copilot/`. Any earlier Streamlit or Python-only UI guidance in this document is superseded by `15_FRONTEND_ARCHITECTURE.md`, `16_UI_UX_SPECIFICATION.md`, and `17_UI_WIREFRAMES.md`. Do not implement Streamlit.

# Architecture and boundaries

## Design
`manifest + optional overrides -> validation/probe -> resolved project model -> shared timeline -> preview/render services -> verification + publishing metadata`.

**Backend:** Python 3.11+; standard library, Pydantic (optional but recommended for schema validation), FFmpeg/FFprobe, Pillow for static previews, NumPy for waveform envelope (or stdlib wave for PCM fixtures). **UI:** Streamlit for Import / Review / Render. **Waveform component:** Wavesurfer.js Regions plugin embedded as a small custom Streamlit component with bidirectional state, or a comparably tested browser component. Streamlit built-in audio alone does not supply draggable regions. Do not build a second rendering engine in JS.

## Proposed package
```
wrld_video/
  models.py         # manifest/overrides typed contracts
  ingest.py         # file discovery, paths, audio probing
  timeline.py       # per-track starts/durations and Short offsets
  colors.py         # named profiles, mood mapping, bounded grading
  preview.py        # still and short motion preview via shared filters
  waveform.py       # downsampled peak envelope and segment audio endpoint
  filters.py        # FFmpeg filter graph builders (no shell=True)
  render.py         # compilation, shorts, thumbnails
  metadata.py       # chapter, per-short descriptions, CSV
  verify.py         # ffprobe, decoded audio/video checks
  storage.py        # atomic overrides saves, output paths
  cli.py            # validate, preview, render
studio_app.py       # Streamlit three-screen UI
frontend/waveform/  # optional small Wavesurfer.js component
config/color_profiles.json
schemas/project.schema.json
examples/
tests/
```

## Critical contracts
- `Project` has immutable identity/source paths and mutable visual overrides; audio duration and track offsets are **derived** from FFprobe, never trusted from user-entered JSON.
- `Timeline` is computed once and shared across compilation titles, chapters, Short extraction, progress, and reports.
- `Short` references stable track ID, stable short ID, `start_seconds` and `end_seconds` relative to that track. Keep fractional seconds.
- Preview and final render use one resolved visual-settings object and common filter builders. Do not duplicate profile or layout logic.
- Separate *planned settings* from *measured render results*. Reports record command/version, input hashes or size/mtime, duration, codecs, settings, warnings and status.
- CLI remains usable without Streamlit/Node. UI must call library functions, not shell out to the CLI or rewrite media algorithms.
- No global `cwd` assumptions. Use `subprocess.run([...], check=True)` with argument arrays; FFmpeg filter escaping and subtitle paths require Windows tests.

## Compatibility
Legacy v2 manifest uses `album_title`, `background`, `tracks[{title,file,shorts}]`. Provide an adapter so these still work; avoid silently replacing existing album JSON. Existing WRLD-FI canonical JSON nests tracks under `album.tracks` and contains many extra fields. Treat it as read-only external source and introduce a later adapter; do not force its schema into the POC.

## v1.1 orchestration boundary
The Streamlit UI invokes application services for validate/preview/save/queue/cancel. An in-process job coordinator is the single writer of job state and owns at most one FFmpeg subprocess; render workers receive immutable job snapshots and emit results. FFmpeg operations live behind a testable subprocess adapter. No C#/.NET, Docker, microservices, or distributed queue in this POC. See `10_...` and `11_...` contracts.

## v1.2 architecture rule
Use a ports-and-adapters layout: domain and application use cases must not depend on Streamlit, FFmpeg implementations, filesystem implementations, or Music Analyzer code. CLI and UI invoke the same use cases. See `14_MICROSERVICE_READY_ARCHITECTURE.md` for dependency direction and package layout.
