# 18 — Custom Color Treatments (v1.4 normative)

## Scope and UX
In the Review screen, `ColorTreatmentEditor` supports exactly three modes: `auto` (derive from track mood), `preset` (named palette), and `custom` (user-selected color). Preserve existing preset swatches, add `<input type="color">` (native picker) paired with an editable HEX field, a bounded intensity slider, and **Reset to Mood**. The eyedropper may be offered only when browser support exists, with a fallback. Show the effective color and active mode, not merely a preset label. Changing controls updates the lightweight UI preview immediately and requests an authoritative backend preview asynchronously; mark approximations clearly. Never mutate the original image or canonical album JSON.

## Contract
Store overrides by stable Short ID in `render_overrides.json`. Use a discriminated object to avoid conflicting fields:

```json
{"color_treatment":{"mode":"custom","hex":"#C38B5F","intensity":0.30}}
```

`auto`: `{"mode":"auto","intensity":0.30}`; `preset`: `{"mode":"preset","preset":"warm","intensity":0.30}`. `original` is a valid preset and means no tint. `hex` must match `^#[0-9A-Fa-f]{6}$` and be normalized to uppercase; intensity finite within 0.0–0.6 inclusive (safe POC range, adjustable by later explicit contract revision). Reject invalid backend payloads with 422 and do not save partial changes. The legacy `color_profile`/`color_intensity` fields must be accepted through a documented adapter, but never mixed silently with the new object; if both are supplied, return an explicit conflict. No automatic migration that overwrites source files. Define and test mood precedence and unknown-mood fallback.

## Rendering consistency
Backend owns a single canonical transform specification for both preview and final FFmpeg render (color, blend method, intensity, color space). The browser overlay is illustrative only. The final renderer and authoritative preview MUST share transform-generation code; verify with sampled frames using tolerance-based comparison. Preserve blurred background and centered original artwork for portrait Shorts; decide whether tint applies to background, foreground, or both and expose this consistently in previews (POC default: both).

## UX acceptance and tests
- Custom color picker and HEX field synchronize bidirectionally; incomplete typing does not corrupt saved state.
- Mode changes retain draft values but serialize only fields relevant to selected mode.
- Reset to Mood sets `mode=auto`; Apply to Track requires confirmation and enumerates affected Short IDs.
- Save/reload retains custom HEX, intensity, and mode per Short; changing Short never leaks values into another.
- Keyboard accessible with labeled picker, input, slider and focus rings; browser unsupported eyedropper gracefully hidden.
- Unit, React Testing Library, Playwright, API contract, and FFmpeg visual integration tests cover validation, override revision conflict, and preview/render agreement.


## v1.5 preview precision
Follow `22_PREVIEW_AND_COLOR_REGRESSION.md`: browser preview is approximate, debounced server-rendered still is authoritative, motion preview is on demand. Do not assert CSS and FFmpeg output are pixel-identical. Cross-codec ProRes comparison is optional, not a POC gate.

## v1.6 auto-color resolution override
The v1.6 `25_COLOR_RESOLUTION.md` is normative for `auto`: free-form mood text is accepted; album palette takes precedence over weak text classification, with numeric features only if supplied; unknown text falls back safely without validation failure. Older fixed mood enum/profile lists are not required input vocabulary. User `preset` and `custom` modes still follow this document.
