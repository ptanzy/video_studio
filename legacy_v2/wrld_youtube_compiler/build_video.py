#!/usr/bin/env python3
"""Build a simple 12-track YouTube compilation from a JSON manifest."""
import argparse
import json
import math
import re
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path


def run(command, cwd=None):
    subprocess.run(command, cwd=cwd, check=True)


def ass_time(seconds):
    centis = round(seconds * 100)
    h, rem = divmod(centis, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02}:{s:02}.{cs:02}"


def chapter_time(seconds):
    s = round(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h:02}:{m:02}:{sec:02}" if h else f"{m:02}:{sec:02}"


def escape_ass(value):
    return re.sub(r'([{}\\])', lambda m: {'{': '(', '}': ')', '\\': '/'}[m.group()], value).replace('\n', ' ')


def write_ass(path, tracks, starts, durations):
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,52,&H00FFFFFF,&H00FFFFFF,&H00202020,&H90000000,0,0,0,0,100,100,0,0,1,3,2,2,80,80,90,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for track, start, duration in zip(tracks, starts, durations):
        lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(start + duration)},Default,,0,0,0,,{escape_ass(track['title'])}\n")
    path.write_text(''.join(lines), encoding='utf-8')


def make_artwork(image, out):
    """Generate YouTube thumbnail and small landscape preview."""
    for name, width, height in [('thumbnail_1280x720.jpg', 1280, 720), ('preview_320x180.jpg', 320, 180)]:
        run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-i', str(image),
             '-vf', f'scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}',
             '-frames:v', '1', '-q:v', '3', str(out / name)])


def short_specs(data, tracks, durations, parser):
    specs = []
    for i, track in enumerate(tracks):
        segments = track.get('shorts', [])
        if not isinstance(segments, list):
            parser.error(f'Track {i+1}: shorts must be an array')
        for j, segment in enumerate(segments, 1):
            if not isinstance(segment, dict):
                parser.error(f'Track {i+1}, short {j}: expected an object')
            try:
                start = float(segment['start_seconds'])
                end = float(segment['end_seconds'])
            except (KeyError, ValueError, TypeError):
                parser.error(f'Track {i+1}, short {j}: provide numeric start_seconds and end_seconds')
            if not (math.isfinite(start) and math.isfinite(end)):
                parser.error(f'Track {i+1}, short {j}: timestamps must be finite')
            if not (0 <= start < end <= durations[i] + 0.005):
                parser.error(f'Track {i+1}, short {j}: range {start}-{end} exceeds track duration {durations[i]:.3f}')
            if end - start > 180:
                parser.error(f'Track {i+1}, short {j}: duration exceeds 180 seconds')
            specs.append({'track_index': i, 'short_index': j, 'start_seconds': start,
                          'end_seconds': end, 'title': segment.get('title') or track['title']})
    return specs


def make_short(image, wav, spec, out, crf):
    """Render portrait from the SAME source artwork and audio, not from a lossy MP4 crop."""
    duration = spec['end_seconds'] - spec['start_seconds']
    # Separate portrait layout ensures that titles remain readable and uncropped.
    title = str(spec['title']).replace('\n', ' ')
    with tempfile.TemporaryDirectory(prefix='wrld_short_') as temp:
        work = Path(temp)
        write_ass(work / 'title.ass', [{'title': title}], [0], [duration])
        run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
             '-loop', '1', '-framerate', '30', '-i', str(image),
             '-ss', f"{spec['start_seconds']:.6f}", '-t', f'{duration:.6f}', '-i', str(wav),
             '-filter_complex',
             '[0:v]scale=1080:1920:force_original_aspect_ratio=increase,'
             'crop=1080:1920,format=yuv420p,subtitles=title.ass:force_style=\'Fontsize=42,MarginV=220\'[v]',
             '-map', '[v]', '-map', '1:a:0', '-c:v', 'libx264', '-preset', 'veryfast',
             '-crf', str(crf), '-r', '30', '-c:a', 'aac', '-b:a', '192k',
             '-t', f'{duration:.6f}', '-movflags', '+faststart', str(out)], cwd=work)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('manifest', type=Path, help='JSON manifest path')
    p.add_argument('--output', type=Path, default=Path('output'), help='Output folder')
    p.add_argument('--crf', type=int, default=20, help='H.264 quality, lower is better')
    args = p.parse_args()
    if not (0 <= args.crf <= 51):
        p.error('--crf must be 0..51')
    if not shutil.which('ffmpeg'):
        p.error('ffmpeg not found in PATH')
    manifest = args.manifest.resolve()
    data = json.loads(manifest.read_text(encoding='utf-8'))
    album = data.get('album_title', 'WRLD Music Compilation')
    tracks = data.get('tracks', [])
    if not isinstance(tracks, list) or not (1 <= len(tracks) <= 12):
        p.error('tracks must be a list of 1 to 12 entries')
    base = manifest.parent
    image = (base / data['background']).resolve()
    if not image.is_file():
        p.error(f'Background missing: {image}')
    paths = []
    for i, track in enumerate(tracks, 1):
        if not isinstance(track.get('title'), str) or not track['title'].strip():
            p.error(f'Track {i}: title missing')
        source = (base / track['file']).resolve()
        if not source.is_file():
            p.error(f'Track {i}: missing audio file: {source}')
        paths.append(source)
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    make_artwork(image, out)
    with tempfile.TemporaryDirectory(prefix='wrld_compile_') as tmp:
        work = Path(tmp)
        durations = []
        wav_names = []
        for i, path in enumerate(paths):
            wav = work / f'track_{i:02}.wav'
            run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-i', str(path), '-vn', '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s16le', str(wav)])
            with wave.open(str(wav), 'rb') as reader:
                durations.append(reader.getnframes() / reader.getframerate())
            wav_names.append(wav.name)
        starts = []
        total = 0.0
        for duration in durations:
            starts.append(total)
            total += duration
        concat = work / 'audio.txt'
        concat.write_text(''.join(f"file '{name}'\n" for name in wav_names), encoding='utf-8')
        combined = work / 'combined.wav'
        run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', concat.name, '-c', 'copy', combined.name], cwd=work)
        specs = short_specs(data, tracks, durations, p)
        shorts_dir = out / 'shorts'
        if specs:
            shorts_dir.mkdir(parents=True, exist_ok=True)
        short_results = []
        for spec in specs:
            i, j = spec['track_index'], spec['short_index']
            filename = f'track_{i+1:02}_short_{j:02}.mp4'
            target_short = shorts_dir / filename
            make_short(image, work / wav_names[i], spec, target_short, args.crf)
            short_results.append({**spec, 'file': str(target_short),
                                  'compilation_start_seconds': round(starts[i] + spec['start_seconds'], 3),
                                  'duration_seconds': round(spec['end_seconds'] - spec['start_seconds'], 3)})
        write_ass(work / 'titles.ass', tracks, starts, durations)
        # Run from temp directory to keep subtitle filter paths portable on Windows.
        target = out / 'compilation.mp4'
        run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
             '-loop', '1', '-framerate', '30', '-i', str(image), '-i', combined.name,
             '-vf', 'scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,format=yuv420p,subtitles=titles.ass',
             '-c:v', 'libx264', '-preset', 'veryfast', '-crf', str(args.crf),
             '-r', '30', '-c:a', 'aac', '-b:a', '256k', '-t', f'{total:.6f}',
             '-movflags', '+faststart', str(target)], cwd=work)
    chapters = '\n'.join(f'{chapter_time(start)} {track["title"]}' for start, track in zip(starts, tracks))
    description = f'{album}\n\nTracklist:\n{chapters}\n'
    (out / 'youtube_description.txt').write_text(description, encoding='utf-8')
    (out / 'render_report.json').write_text(json.dumps({
        'album_title': album, 'video': str(target), 'duration_seconds': round(total, 3),
        'shorts': short_results, 'thumbnail': str(out / 'thumbnail_1280x720.jpg'),
        'preview': str(out / 'preview_320x180.jpg'),
        'tracks': [{'title': t['title'], 'source': str(path), 'start_seconds': round(start, 3), 'duration_seconds': round(duration, 3)}
                   for t, path, start, duration in zip(tracks, paths, starts, durations)]
    }, indent=2), encoding='utf-8')
    print(f'Created: {target}\nDescription: {out / "youtube_description.txt"}')


if __name__ == '__main__':
    main()
