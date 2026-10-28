# 20 — v1.4 Acceptance Matrix, Architecture Hardening, and Test Gates

## Architecture and reliability contracts
Maintain React/TypeScript + Vite + Tailwind + WaveSurfer.js frontend, FastAPI application adapter, Python domain/application services and FFmpeg infrastructure adapter. No Streamlit. No analyzer code imports. No Docker, distributed broker, C#, or GPU requirements for POC. All approved headless/API/UI adapters use the same application services. Freeze immutable render requests and record content fingerprints, output paths, and tool versions. Single active FFmpeg render by default; queue and cancel safely. Write output to same-filesystem temporary file, validate with FFprobe and content tests, then atomically promote. Re-runs reuse only validated outputs matching the request fingerprint. Incomplete files must not be accepted as success. Editor state uses atomic replacement + optimistic revisions; workers never edit it. Log JSON events with job ID, stage, timestamp, sanitized error, and durations; avoid sensitive file data in shared logs. Pin frontend and backend dependencies and use the existing `MediaToolchain` capability checks; no `scripts/doctor.py` is currently shipped.

## Contract validation and compatibility
- JSON Schema draft 2020-12 for manifest and override/publishing contracts; Python Pydantic and TypeScript types must be tested against representative valid and invalid fixtures.
- Legacy v2 adapter explicitly maps supported fields; ambiguous values fail with diagnostics. Existing `schemas/manifest-v2.schema.json` is only a structural subset and must not be represented as complete validation.
- CI gates: schema fixtures; Python unit/API tests; frontend typecheck, lint, Vitest; Playwright editor and metadata flows; FFmpeg integration smoke on an available runner. Heavy soak tests may be opt-in/nightly.

## Test matrix
| ID | Area | Automated assertion |
|---|---|---|
| C01 | Custom color | HEX picker/text sync, invalid value rejected, valid save/reload |
| C02 | Color state | Switching Shorts isolates settings; Reset to Mood works |
| C03 | Color rendering | Authoritative preview and final sampled frame within declared tolerance |
| M01 | Metadata edits | Compilation and Short overrides isolated by stable ID; survive regeneration |
| M02 | Chapters | Real durations and order produce correct timestamps; stale edits flagged |
| M03 | Validation | Overlength text, unresolved placeholders, duplicate titles handled per severity |
| M04 | Export | Approved Unicode text matches exported files, CSV escaping safe |
| S01 | State | Concurrent stale save rejected with 409, no lost update |
| R01 | Recovery | Interrupted FFmpeg leaves no accepted partial final output; safe retry |
| R02 | Idempotency | Matching valid output reused; changed input forces new render |
| A01 | Audio | Distinct synthetic tones verify correct track and Short excerpt |
| V01 | Media | FFprobe codec, duration, fps, aspect ratio, audio/video streams |
| P01 | Performance | One FFmpeg process; bounded previews; optional 12-track soak fixture |
| E01 | End-to-end | Import → Review → Metadata → Render with mocked jobs; one real-media smoke |

## Golden-output policy
Never require byte-identical H.264 output across platforms. Use structural FFprobe checks, decoded synthetic-tone frequency checks, sampled frame perceptual/tolerance checks, and stable contract fixtures. Record tested FFmpeg version and tolerances. Golden images must be reviewed and intentionally updated, not silently regenerated in CI. UI screenshots are design references, not production goldens.

## Work unit gates
WU0: inspection only. WU1: foundations. WU2: reusable media/job infrastructure and synthetic proof. WU3: authoritative still-preview/color backend. **WU3A: implementation candidate present, final acceptance pending; project-local album plus individual-track static MP4 export, timeline/chapters/report under the approved `output/` tree, headless entry point, real-media CI, and mandatory *Echoes of Asia* automated plus human playback acceptance. WU3A must not read or produce `youtube_metadata.json`.** WU3B: after exact contract approval, additive v2 flat-image motion, amplitude/RMS bars, sample-boundary track progress, and bounded temporary motion preview while v1 remains unchanged; WU3B has separate generated-media, real-track, and human-review acceptance. WU4: React Import/Review, waveform audition, WU3B effect/preview controls, and revisioned persistence. WU5: Metadata Table/Detail, drafts, validation, approval and `output/metadata/youtube_metadata.json` export using the shared chapters. WU6: integrated Render UX/job HTTP, `output/shorts/`, remaining artifacts, packaging and final POC end-to-end acceptance. WU7: planned layered/title-aware/parallax/atmospheric composition and dedicated editor. Every unit preserves source files and metadata ownership, requires exact test evidence and user approval, and must not claim unexecuted tests passed.


## v1.5 additional gates
| ID | Area | Automated assertion |
|---|---|---|
| X01 | Error contract | Stable typed codes, request IDs, safe HTTP mapping, no hidden success |
| X02 | Storage | Scratch and artifact separation; interruption cannot promote invalid output |
| X03 | Legacy isolation | No runtime import/call of legacy monolithic builder |
| X04 | Color proxy | Immediate approximate UI + authoritative server preview, stale requests ignored |
| X05 | Color regression | Decoded fixed-frame tolerances, recorded color space/encoder; optional ProRes |
| X06 | Metadata grid | Batch selection, edit isolation, confirm bulk actions, Table/Detail persistence |
| X07 | Metadata bounds | Unicode, tags, title/description, placeholders, CSV injection fixtures |
| X08 | Prototype | Import→Review→Metadata→Render simulated path, no real-render claims |
