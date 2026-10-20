# Risks, decisions, and open questions

## Decisions already established
- The goal is to publish test tracks promptly; no WRLD-FI story scenes or A/B workflows in POC.
- One artwork reused across compilation and Shorts; mood grading distinguishes Shorts without needing new image generation.
- Waveform visualizer is compact **beside title**; distinct from the interactive waveform selector used to audition Short clips.
- User can edit only bounded visual settings and Short selection, not audio arrangement.
- Separate render overrides from source album JSON; no source mutation.
- No AI masking/detector evasion features; audio processing is not required for monetization.

## Risks to address
1. **Scope creep:** Streamlit UI + custom JS waveform is the largest nontrivial part. Deliver working CLI before UI.
2. **Streamlit JS integration:** need a reliable bidirectional custom component and region-state synchronization; evaluate available component approach in WU5. Browser playback must obey gesture restrictions.
3. **Performance:** rendering 45–60 min at 1080p with grain/reactive bars can be slow. Use low-res previews, cache envelopes, and avoid rendering entire videos for each edit.
4. **FFmpeg portability:** subtitles/libass, Windows path quoting, unicode and filter escaping. Prefer temp files for complex graphs and cross-platform integration tests.
5. **Precision:** sample-rate conversion, AAC padding and frame boundaries; define tolerances and compare Short audio to known test tones.
6. **Monetization:** no video design guarantees YPP eligibility; rights to music/artwork, AI disclosure and channel-level originality remain separate.
7. **Manifest drift:** existing WRLD-FI canonical schema differs; support v2 adapter first and document a future read-only importer.
8. **Preview mismatch:** static preview can only approximate reactive motion; on-demand motion preview must use same filters as final.
9. **Short length policy:** legacy script allows <=180 s. Keep configurable cap and validate current YouTube requirements before publishing; do not assume all portrait clips will be categorized as Shorts.
10. **Hardware:** no GPU requirement. CPU-only FFmpeg is baseline; optional GPU acceleration only after correctness tests.

## Open decisions (defaults for POC)
- UI stack: Streamlit + small Wavesurfer custom component (default).
- Output location: `output/` sibling to manifest, configurable.
- Excerpt length: default 30 s, user-adjustable within max 180 s; recommend 15–60 s for initial releases.
- Per-Short color intensity: 0.0–0.3 normalized UI range (implementation must define precise filter semantics).
- Motion: zoom to 1.04 over clip/compilation, user may disable; keep title anchored.
- Overwrite: default refuse; explicit confirmation to replace generated files.
- Auto color conflicts: deterministic priority documented by implementation, or original if ambiguous.
