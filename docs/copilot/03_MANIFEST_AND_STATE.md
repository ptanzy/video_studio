# Manifest and persistent editor state

## Strategy
- `manifest.json`: user-authored source-of-truth for album/track identity, ordered audio paths, artwork and initial Short selections.
- `render_overrides.json`: editor-only bounded presentation changes and Short edits; atomic write with backup or temp-file + rename. Do not modify canonical WRLD-FI metadata.
- `render_report.json`: machine-generated observations and outputs; **never** use as user configuration.
- `schema_version`: mandatory for new format; implement explicit migration/legacy adapter.
- The explicitly selected album directory is the project boundary. Persist artwork, audio, artifact, and publishing references relative to that boundary wherever appropriate; reject missing/unreadable paths, traversal, link/reparse escapes, and unsafe source/output aliasing. Do not require a network service or persist the current machine's library/repository prefix.

## Proposed example (illustrative; not supported by legacy v2 until implemented)
```json
{
  "schema_version": "2.0",
  "project": {"brand": "WRLD MUSIC", "channel": "WRLD-FI"},
  "album": {"id": "WRLD-FI-TEST-001", "title": "Test Compilation 001", "artist": "WRLD-FI", "artwork": "artwork/cover.png"},
  "video": {
    "compilation": {"resolution": [1920,1080], "fps": 30, "show_title": true, "progress": true, "reactive_bars": {"enabled": true, "position": "left_of_title", "count": 9}, "motion": {"type": "slow_zoom", "zoom_end": 1.04}, "grain": {"enabled": true, "strength": 0.025}},
    "shorts": {"resolution": [1080,1920], "fps": 30, "layout": "blurred_background", "color_profile": "auto", "show_title": true, "progress": true, "reactive_bars": true}
  },
  "tracks": [
    {"id": "T01", "number": 1, "title": "First Test Track", "file": "tracks/01.wav", "music": {"mood": ["reflective", "peaceful"]}, "shorts": [{"id": "T01-S01", "start_seconds": 45.2, "end_seconds": 75.2, "title": "First Test Track — Highlight", "fade_in_seconds": 0.25, "fade_out_seconds": 0.5}]}
  ],
  "publishing": {"visibility": "private", "generate_chapters": true, "generate_short_descriptions": true, "generate_upload_csv": true}
}
```

## Override example
```json
{
  "schema_version": "1.0",
  "base_manifest_sha256": "<computed-on-save>",
  "shorts": {"T01-S01": {"start_seconds": 48.0, "end_seconds": 78.0, "color_profile": "cool", "color_intensity": 0.15, "zoom_enabled": true}},
  "tracks": {"T01": {"reactive_bars_enabled": true}}
}
```
`<computed-on-save>` is a documentation placeholder; production must use a real hash. Overrides should include only changed values, not duplicate the whole album. Warn on source manifest hash mismatch and allow explicit rebase/reset; do not silently apply stale overrides to different tracks.

## Validation
- Stable unique track and short IDs; order explicit; no duplicate IDs; nonempty titles; file existence; valid images/audio; finite numbers (reject NaN/Infinity); `0 <= start < end <= actual track duration` with small codec tolerance; positive excerpt length and a configurable maximum (legacy v2: 180 s). Fade-in + fade-out must not exceed excerpt length.
- Restrict profiles to known names: `original`, `cool`, `warm`, `lavender`, `teal`, `dark`; `auto` derives from mood with documented precedence and falls back to original if ambiguous.
- Restrict intensity/zoom/grain to safe bounded ranges and clamp only UI inputs; invalid manifest values should generate explicit validation errors.
- File paths are data, not commands; escape user titles for FFmpeg subtitles, CSV, and description output.

## v1.1 binding requirements
`10_CONTRACTS_AND_COMPATIBILITY.md` is normative for schema validation, override revisions, atomic saves, legacy adaptation and frozen job snapshots. Do not assume an atomic replace alone solves concurrent editor sessions. Never mutate canonical album JSON.

## v1.2 metadata boundary
The canonical album manifest, analysis metadata sidecar, mutable editor overrides, immutable render request, and render result are distinct contracts. Preserve recording identity; do not require custom analysis metadata to be embedded in WAV. Support absent analysis metadata. See doc 14.


## v1.4 editor override extensions
Color uses discriminated `color_treatment` (auto/preset/custom), not a free-form color_profile string; see doc 18. Approved YouTube text uses `publishing_metadata` overrides keyed by stable compilation/Short IDs; see doc 19. These belong in editor overrides, not the canonical album manifest. A generated metadata draft is not a render report or a published record. Keep optimistic revision, atomic writes, stale-source detection and immutable render snapshots.

## v1.6 authoritative clarification
The minimal manifest schema (`contracts/schemas/manifest-v2.schema.json`) and the **rich illustrative metadata contract** (`docs/examples/metadata_contract.example.json`) are different shapes. Do not claim direct schema compatibility; implement an explicit adapter and test it. Source creative album JSON, optional Analyzer sidecar keyed by recording ID, editor overrides, generated publishing drafts, immutable render snapshots, and render reports are distinct. Unknown `mood_text` is valid unrestricted text. Supplied `energy`, `tension`, `brightness`, `valence`, `arousal` are optional nullable finite [0,1] values. Preserve original inputs; no invented measured values. See 24–26.

## WU3A render-contract boundary

Doc 38 requires the approved versioned product render request for album and individual-track export. Neither the illustrative JSON above nor `manifest-v2.schema.json` is that request. The headless interface receives an explicit runtime album-project path; portable persisted contracts do not embed its machine-specific absolute prefix. Decision 1 approves `video-manifest-v1.schema.json` (`wrld-video-album/1.0`), `video-export-request-v1.schema.json` (`video-export-request/1.0`), and `video-export-result-v1.schema.json` (`video-export-result/1.0`). The portable manifest holds stable identity, project-relative artwork/audio, ordered tracks, optional stable clip definitions, and an allowlisted profile ID; the immutable request selects album/track and profile; the result contains factual verified artifacts/timeline only. Probed durations, normalized sample counts, offsets, tool identity, resolved runtime paths, and measured output belong in the frozen job snapshot/result, not portable publishing metadata. WU3A does not read any `youtube_metadata.json`.

The current `wrld-video-album/0.1-draft` is proposed as diagnostic adapter input, not automatically valid render input. In particular, the inspected *Echoes of Asia* draft lacks stable track/album IDs and references unprefixed PNG names that do not exist. It requires explicit migration/approval; never guess filenames or rewrite it silently.
