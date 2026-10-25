# Media quality, regression, and resource testing — v1.1

## Three verification layers
1. **Structural:** ffprobe JSON: H.264 video + AAC audio, dimensions 1920x1080 or 1080x1920 in production, 30 fps nominal, yuv420p, nonzero streams/duration, sensible audio sample rate; test resolution may be reduced. Explicitly define tolerances (e.g., video duration within 2 frames + 0.15 s of expected; adjust only with documented encoder evidence).
2. **Audio content:** synthetic per-track sine tones at distinct frequencies; decode rendered excerpts to PCM and verify dominant spectral energy near expected tone. Test wrong-track selection, offset, fade boundaries, first/last samples with codec-tolerant windows, and compilation transition order. For accurate excerpt boundaries, use a time-varying fixture (chirp or distinct tone segments), not a constant tone alone.
3. **Visual:** fixed generated artwork with colored corners and known title positions. Extract frames at deterministic timestamps. Compare crop/blur, title visibility, progress positions, and reactive bars with perceptual/MAE/SSIM tolerances; mask inherently nondeterministic areas (film grain), or disable grain in deterministic golden tests. Store small versioned golden PNGs only after human approval. Do not assert byte-for-byte MP4 identity across encoders/platforms.

## Fixture/test tiers
- Unit: no FFmpeg or browser; deterministic, fast; mocks for subprocess, file IO failure, job scheduler, and preview generation.
- Media integration: FFmpeg/FFprobe required; 2–4 second WAVs, small test frames, temp dirs, no copyrighted assets. Validate actual decoding and content, not merely file existence.
- UI/browser: Wavesurfer component with Playwright: region move, resize, start/end exactness, playback stop, replay, multiple regions, track switch, persisted state. Browser tests are required before WU5 completion, not during WU1.
- Manual Windows acceptance: WU3A requires the real 12-track *Echoes of Asia* project path to be supplied explicitly, the album plus at least one individual full-track MP4 to be published in the approved project-local tree, both artifacts to be probed/decoded through EOF, and the album to be checked at chapter/track transitions and reviewed in VLC or Windows Media Player. Confirm the corrected supplied background, ordered audio, and source preservation. An external acceptance harness may compare the publishing file before/after, but the WU3A application must not open, validate, hash, or write `youtube_metadata.json`. Record project/output paths as environment-specific evidence, not portable schema defaults. WU4–WU6 later add reopen-after-edit, integrated cancellation/recovery UI, Shorts, and 9:16 acceptance.
- Soak/performance: optional nightly/manual profile of 12 synthetic tracks and multiple Shorts; cap concurrent FFmpeg at one; monitor peak RSS, file descriptors/handles, temp disk usage, and cleanup. Set thresholds based on baseline machine measurements, not invented universal limits.

## Failure injection tests
- Force FFmpeg nonzero exit after temp write; assert final untouched, status failed, retry safe.
- Crash after promotion but before state update; startup reconciliation validates and repairs state.
- Inject invalid/corrupt partial MP4, disk write failure, stale override revision, manifest change, and cancellation; assert no false success.
- Run repeated identical job and assert reuse, then modify input/config and assert cache invalidation.

## CI gates
- `python -m pytest -m 'not media and not browser'` for fast unit suite; `python -m pytest -m media` for real FFmpeg tests; `python -m pytest -m browser` after UI component exists. `ruff check .` and schema validation mandatory.
- GitHub Actions Windows + Ubuntu. Pin Python minor and dependencies; log FFmpeg version/capabilities. Golden image tests may require controlled FFmpeg baseline or tolerant comparisons and OS-specific baselines.
- Pure core coverage target >=80%, report other areas separately. Never claim tests passed unless actually run; skip markers must explain prerequisites.
