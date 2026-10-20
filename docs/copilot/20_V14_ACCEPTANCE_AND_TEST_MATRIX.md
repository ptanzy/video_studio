# 20 — v1.4 Acceptance Matrix, Architecture Hardening, and Test Gates

## Architecture and reliability contracts
Maintain React/TypeScript + Vite + Tailwind + WaveSurfer.js frontend, FastAPI application adapter, Python domain/application services and FFmpeg infrastructure adapter. No Streamlit. No analyzer code imports. No Docker, distributed broker, C#, or GPU requirements for POC. All CLI/API/UI use the same application services. Freeze immutable render requests and record content fingerprints, output paths, and tool versions. Single active FFmpeg render by default; queue and cancel safely. Write output to same-filesystem temporary file, validate with FFprobe and content tests, then atomically promote. Re-runs reuse only validated outputs matching the request fingerprint. Incomplete files must not be accepted as success. Editor state uses atomic replacement + optimistic revisions; workers never edit it. Log JSON events with job ID, stage, timestamp, sanitized error, and durations; avoid sensitive file data in shared logs. Pin frontend and backend dependencies and document FFmpeg capabilities with `scripts/doctor.py` in WU1.

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
WU0: inspection only; identify conflicting old Streamlit references and contract gaps. WU1: schemas, toolchain, tests, API and UI skeleton. WU2: render core and recovery. WU3: visuals including custom color. WU4: Review UI and preview persistence. WU5: waveform audition. WU6: metadata screen and exports, end-to-end integration. Each work unit requires a change summary, exact test commands/results, unresolved risks, and user approval before next. Do not claim unexecuted tests passed.


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
