# WRLD YouTube Compilation Builder — MVP

Generate a YouTube-ready 1080p H.264 MP4 from 1–12 audio tracks, a single background image, and a JSON manifest. Current track title appears near the bottom of the screen. No crossfades; original audio files are never modified.

## Requirements
- Python 3.10+ (standard library only)
- FFmpeg executable in PATH, built with `libx264` and the `subtitles`/`libass` filter (`ffmpeg -filters` should show `subtitles`).
- Windows, macOS, or Linux.

## Input folder

```text
my_album/
  manifest.json
  background.jpg
  tracks/
    01.wav
    02.wav
    ...
```

Copy `manifest.example.json` to `my_album/manifest.json` and edit. Paths are relative to the manifest folder. List tracks in **the desired playback order**. Up to 12 WAVs (other FFmpeg-supported audio formats may work).

## Run

```powershell
python build_video.py "C:\music\my_album\manifest.json" --output "C:\music\my_album\rendered"
```

Outputs:
- `compilation.mp4`: 1920×1080, 30fps, H.264, AAC 256kbps
- `youtube_description.txt`: tracklist with chapter timestamps
- `render_report.json`: sources, durations, start times

Upload the MP4 through YouTube Studio and paste the description. Uploading and YouTube authentication are **not** included in this MVP.

## Notes and limitations
- Rendering a 40–60 minute static-background video still takes time and disk space; this is a basic CPU H.264 implementation.
- Audio is converted to 48kHz stereo PCM before concatenation, then encoded to AAC for MP4. No mastering, normalization, remixing, or crossfades.
- Chapters use whole-second timestamps. For YouTube chapters, first timestamp must be 00:00, at least three chapters should exist, and chapters must meet YouTube's minimum duration requirements. With fewer than three tracks, the description still lists timestamps but may not create YouTube chapters.
- Image is scaled/cropped to fill 16:9. Use artwork you have the rights to publish.
- Video has static background with changing titles, not a waveform or animation. This intentionally minimizes dependencies.
- Subtitle text is rendered using FFmpeg's libass filter; the Arial fallback depends on system fonts.
- If you receive `No such filter: subtitles`, install an FFmpeg build with libass enabled.
- Rendering does not guarantee YouTube monetization. Confirm commercial rights and make applicable synthetic-content disclosures.

## Shorts and artwork (v2)

Add optional `shorts` arrays to individual track objects in the manifest (see `manifest.example.json`). Each short uses **seconds relative to that track**, not the full compilation. For example, track 5 `start_seconds: 45` and `end_seconds: 75` generates a 30-second Short using the same source background and corresponding track audio. Multiple shorts per track are supported; omit `shorts` to skip a track. Requested ranges must fit inside the track, with a maximum of 180 seconds per Short.

Additional outputs:
- `shorts/track_05_short_01.mp4`: vertical 1080×1920 H.264/AAC video with centered-cropped album artwork and the short's title.
- `thumbnail_1280x720.jpg`: landscape thumbnail candidate from the background image.
- `preview_320x180.jpg`: small landscape preview from the same image.
- `render_report.json`: also includes each Short's track-relative start/end, compilation-relative start, duration, and output path.

**Note:** The shorts are re-rendered from the original background and the selected audio segment, rather than cropped from the finished compilation. This preserves audio quality and keeps titles readable in portrait format while matching the main video's design. The image files contain no additional text overlays. YouTube Shorts classification and monetization depend on YouTube's rules and account eligibility, not only the file's dimensions. Uploading is manual.
