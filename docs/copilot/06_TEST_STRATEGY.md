# Test strategy and local setup

## Requirements and setup (Windows PowerShell)
- Python 3.11 or newer and the repository-configured FFmpeg **and FFprobe** executables; FFmpeg needs libx264 and an AAC encoder. The `subtitles`/libass filter is required only by a later approved text-rendering scope. Install Node.js LTS only when implementing the React frontend.
- From repository root:
```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
ffmpeg -version
ffprobe -version
ffmpeg -filters | Select-String subtitles
python -m pytest -q
```
- Use the checked-in backend packaging metadata and lock/constraint policy; do not restore obsolete Streamlit requirements. Prefer standard library where practical. Do **not** install torch, Demucs, librosa, paid SDKs, cloud clients, or analyzer dependencies for this POC.
- On macOS/Linux use the equivalent virtual-environment activation and `python -m pip install -e '.[test]'`.

## Test pyramid
1. **Pure unit tests (fast; no FFmpeg):** manifest parsing/legacy adapter; stable IDs; relative paths; mood precedence/fallback; bounded settings; short region move/resize and clip constraints; timeline offsets; timestamp formatting; ASS escaping; metadata text/CSV; override merge and atomic save; cache key logic.
2. **FFmpeg integration tests (local/CI when available):** generate synthetic 2–4 s PCM WAV sine tones and a PNG image using Python. WU3A renders tiny album/track static videos; later approved Shorts work adds Short renders. Probe streams/durations/dimensions and audio ordering/content. Avoid external media downloads.
3. **UI/component tests:** React/WaveSurfer browser/component tests cover region drag, resize, play-end boundary, replay, track switch, and state round-trip. Use Playwright for critical browser flows from WU4 onward.
4. **Manual smoke test:** Windows with actual WAV and artwork; long title, Unicode, 12 tracks, multiple Shorts, reopen overrides, generate preview, render, review first/last 2 seconds and chapter boundaries.

### WU3A test gate

WU3A adds a required headless video-export tier before browser work: contract/unit tests for the approved manifest/request/result versions, album and track requests, explicit album-project selection, project-relative portability and containment, the approved `output/` tree, normalized sample timeline/chapter formatting, deterministic names, collision/reuse/report-catalog behavior, and metadata ownership; tiny generated multi-track and individual-track real FFmpeg renders; transition-content checks; structural probe; full audio/video decode through EOF; cancellation/recovery/promotion failures; and Windows/Ubuntu media execution. Tests must prove the WU3A application never opens, validates, migrates, writes, or creates `youtube_metadata.json`. Tests must vary project/library/channel-like locations, separate the repository from the album path, and attack traversal/link/reparse escape. CI fixtures remain generated and must not use user music. Final acceptance separately uses the real *Echoes of Asia* album plus at least one full-track export on Windows and requires documented human album playback review; automated tests alone cannot close WU3A. See Doc 38.

### WU3B test gate

After Doc 39's exact contract approval, WU3B adds additive v2 schema/fixture tests without modifying v1; pure camera/envelope/frame-boundary tests; tiny generated-media tests for each effect alone, combined, and disabled; decoded-frame checks for crop bounds, silence/pulse response, placement, monotonic progress and sample-boundary resets; audio-order/content regression; profile-qualified identity/reuse/collision tests; cancellation/recovery/private-preview ownership tests; and Windows/Ubuntu FFmpeg coverage. Record the exact supported filter capability before implementation selects a control-stream mechanism. Final WU3B acceptance requires a bounded real *Echoes of Asia* motion preview and one full real track to pass probe/full decode plus documented human playback review. It does not close or substitute for WU3A's separate full-album acceptance. See Doc 39 Section 10.

## Required fixtures
- Tiny WAV fixtures with distinguishable frequencies (e.g. 220 Hz and 440 Hz) to detect wrong-track Short extraction; silence fixture; mono and stereo fixture; short (<30 s) track; one invalid audio file.
- PNG image generated programmatically (no copyright concerns); image with distinct colored corners to validate portrait crop/blur; long/unicode title strings.
- Use temporary directories and deterministic seeds; never use user music in automated tests.

## Acceptance tests / cases
| ID | Scenario | Expected |
|---|---|---|
| T01 | Legacy v2 manifest | Validated and adapted, original ordering retained |
| T02 | New manifest | Correct IDs, source paths, defaults |
| T03 | Short track 2, 0.5–2.0 s | Exactly track 2 audio excerpt, correct offset |
| T04 | Move 30 s region to end | Length preserved; no overrun |
| T05 | Resize handles past boundaries | Invalid move blocked; valid bound retained |
| T06 | Audio selection play | Starts at selection start; stops at end; replay works |
| T07 | Mood unknown/ambiguous | `original` profile, no guess |
| T08 | Override reload | Same visuals and Short times restored |
| T09 | Rendered compilation | WU3A: correct codecs, 16:9 dimensions, duration, audio order, chapter ordering, and full decode |
| T10 | Rendered Short | 9:16 dimensions, correct duration, audio stream |
| T11 | Missing/corrupt file | Clear validation error; no success report |
| T12 | Unicode/Windows path | Render succeeds with safe text escaping |
| T13 | Title + bars + progress | No visual collision, track reset verified |
| T14 | Preview/final same profile | Matched grade/layout on sampled frame |
| T15 | Cancel/failure | Partial output not reported as completed |

## CI and quality gates
- GitHub Actions matrix: Windows + Ubuntu, Python 3.11 and 3.12 (if practical). Install/configure FFmpeg and FFprobe. Run the repository's documented Ruff, pytest, contract, and coverage commands against `wrld_video_studio`; require `subtitles` only when an approved text-rendering scope uses it.
- Set initial coverage gate **>=80% for pure core modules** (models/timeline/colors/metadata/overrides); integration and UI coverage separately reported. Do not inflate coverage by excluding untested core paths.
- For WU1–WU3A no UI/browser automation is required. WU3A instead requires its Windows real-album manual playback checklist. From WU4 waveform work onward, include browser tests and the applicable Windows manual checklist.
- Tests must not depend on network, Suno, YouTube, paid APIs, GPUs, or source album files. CI can skip FFmpeg integration tests only with explicit documented reason, never silently.

## v1.1 binding requirements
Use `12_VISUAL_AUDIO_REGRESSION.md` for structural/audio/visual golden tests, failure injection, CI tiers, and resource boundaries. Use `13_ENVIRONMENT_AND_DELIVERY.md` for reproducible installation and doctor command. Golden media comparisons should be tolerant and controlled, not exact MP4 hashes.

## v1.2 architecture/contract test gate
Add fake-port application tests, contract schema/migration tests, UI-vs-CLI request equivalence tests, no-Streamlit/no-FFmpeg import-boundary checks, and tests proving operation without Music Analyzer metadata. See doc 14.


## v1.4 superseding testing setup
Earlier Streamlit-specific setup and UI tests are obsolete. Backend: Python 3.11+, `pytest`, `pytest-cov`, Pydantic/JSON Schema, FastAPI API tests, FFmpeg/FFprobe. Frontend: Node.js LTS, React + TypeScript, Vitest + React Testing Library, Playwright, typecheck/lint. Pin dependencies and commit lockfiles; define exact commands during WU1 in root README/CI. Cover color picker + metadata contracts using document 20. Unit tests use mocked render ports; one opt-in FFmpeg smoke uses synthetic WAVs and generated images. Never require live AI or cloud APIs.

## v1.6 additional test gates
Require adapter/identity tests (canonical creative JSON, absent/mismatched Analyzer sidecar, stable recording IDs), unknown/free-form Unicode mood tests, nullable feature tests, deterministic album-palette resolver and fallback tests, and publishing draft precedence/approval/persistence tests. Test supplied-vs-generated description, exact character limits, Unicode, placeholders, chapter regeneration, and batch edits. Test the rich example as adapter input and minimal manifest against its actual schema **separately**. No live LLM, GPU, or network required. See 24–26.

## v1.7 mandatory checks
Apply docs 27–30: accessible split-view UI, inline/batch metadata boundaries, duplicate imports and SHA-256 change detection, schema/type drift in CI, MSW/React Playwright smoke, mock worker reconnection, and real FFmpeg verification with synthetic fixtures. No passing claim without actual test run evidence.
