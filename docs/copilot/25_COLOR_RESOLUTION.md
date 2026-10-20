# 25 — Deterministic color resolution (v1.6 normative)

## Goal
Choose a sensible album-coherent visual treatment without requiring any fixed emotion labels. Mood/emotion is unrestricted prose, never an enum. Unknown strings MUST NOT cause import failure or an arbitrary saturated color.

## Precedence
1. User-approved `color_treatment` override (custom HEX or named preset) for the exact Short/track.
2. Explicit valid per-track visual preference.
3. Album visual palette, optionally weighted by **provided** numeric brightness/energy/tension and recognized mood concepts.
4. Explicit album-level default preset.
5. `original` artwork with intensity 0. No LLM dependency and no random fallback.

For `auto`, choose from supplied album palette **first**. Free-form emotion is a weak, optional hint; unknown words are ignored, not rejected. If numeric features are missing, do not invent them. If palette data is unusable, preserve the original image. Numeric values are optional finite [0,1] features. Do not equate energy with color temperature automatically.

## Output contract (proposed)
```json
{
  "mode": "auto",
  "resolved_hex": "#71869A",
  "intensity": 0.18,
  "source": "album_palette",
  "reason": "Fog-blue palette chosen with supplied low energy",
  "resolver_version": "1.0",
  "input_fingerprint": "<sha256>"
}
```
The HEX/intensity above are illustrative, **not** a mandated mapping for any track. `mode` and override shapes must remain compatible with `18_CUSTOM_COLOR_TREATMENTS.md`; the resolved object is computed render data, not a mutation of canonical input.

## UX
Review page displays color swatch, selected mode, source/reason, custom color picker + HEX input, intensity, Reset to Auto, and before/after comparison. Mark unknown mood terms as informational; show fallback reason. Browser proxy preview may approximate the result, but FFmpeg preview is authoritative; use the same frozen resolved parameters for final render.

## Tests
- Unknown Unicode mood string and missing numbers produce valid deterministic fallback.
- Palette names/HEX entries validated; invalid HEX or out-of-range intensity rejected.
- Same inputs + resolver version => same color and intensity.
- User custom/preset override wins and survives save/reload/re-render.
- Empty palette + unknown mood => original artwork, intensity 0.
- Compare FFmpeg-confirmed decoded frames under documented tolerance; avoid bitwise encoded-video equality and avoid assuming codecs reproduce pixel values identically.
