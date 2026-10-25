# Risks, decisions, and open questions

## Decisions already established
- The goal is to publish test tracks promptly; no WRLD-FI story scenes or A/B workflows in POC.
- One artwork reused across compilation and Shorts; mood grading distinguishes Shorts without needing new image generation.
- Waveform visualizer is compact **beside title**; distinct from the interactive waveform selector used to audition Short clips.
- User can edit only bounded visual settings and Short selection, not audio arrangement.
- Separate render overrides from source album JSON; no source mutation.
- No AI masking/detector evasion features; audio processing is not required for monetization.

## Risks to address
1. **Scope creep:** deliver the approved WU3A headless album/track export before React workflow work; do not pull Shorts, animation, or upload into it.
2. **WaveSurfer integration:** WU4 needs reliable region-state synchronization and browser playback gesture handling; it must consume application services rather than media logic in React.
3. **Performance:** rendering 45–60 min at 1080p with grain/reactive bars can be slow. Use low-res previews, cache envelopes, and avoid rendering entire videos for each edit.
4. **FFmpeg portability:** subtitles/libass, Windows path quoting, unicode and filter escaping. Prefer temp files for complex graphs and cross-platform integration tests.
5. **Precision:** sample-rate conversion, AAC padding and frame boundaries; define tolerances and compare Short audio to known test tones.
6. **Monetization:** no video design guarantees YPP eligibility; rights to music/artwork, AI disclosure and channel-level originality remain separate.
7. **Manifest drift:** existing WRLD-FI canonical schema differs; support v2 adapter first and document a future read-only importer.
8. **Preview mismatch:** static preview can only approximate reactive motion; on-demand motion preview must use same filters as final.
9. **Short length policy:** legacy script allows <=180 s. Keep configurable cap and validate current YouTube requirements before publishing; do not assume all portrait clips will be categorized as Shorts.
10. **Hardware:** no GPU requirement. CPU-only FFmpeg is baseline; optional GPU acceleration only after correctness tests.

## Open decisions (defaults for POC)
- UI stack is locked: React + TypeScript + Vite + Tailwind + WaveSurfer.js; no Streamlit.
- WU3A output boundary is locked to `<album-project>/output/`; only approved filenames/subdirectories beneath it remain configurable. Later project initialization may configure/select music-library roots and channels, but may not change an existing project's containment rules implicitly.
- Excerpt length: default 30 s, user-adjustable within max 180 s; recommend 15–60 s for initial releases.
- Per-Short color intensity: 0.0–0.3 normalized UI range (implementation must define precise filter semantics).
- Motion: zoom to 1.04 over clip/compilation, user may disable; keep title anchored.
- WU3A collision policy: verify/reuse an identical fingerprint; otherwise refuse with `OUTPUT_EXISTS`. No force-overwrite or confirmation-to-replace path exists in WU3A. Any later replacement workflow requires a separately approved controlled and recoverable policy.
- Auto color conflicts: deterministic priority documented by implementation, or original if ambiguous.

WU3A's approved resolutions are centralized in Doc 38 Section 15: source/request/result/report schemas; the `youtube-1080p30-v1` profile; contain/black-pad image fit; sample-count timeline, floored chapter text and no MP4 embedding; exact output names/layout/collision/reuse; the headless command; and deferral of title typography. The corrected current *Echoes of Asia* artwork resolves the historical *Lanterns Across Asia* mismatch subject to normal file validation. Do not apply older illustrative defaults instead. WU3A has no publishing-metadata responsibility and must not read any `youtube_metadata.json`.
