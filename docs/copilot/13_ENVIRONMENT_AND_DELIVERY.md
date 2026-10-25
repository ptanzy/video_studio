# Reproducible environment and delivery — v1.1

## Toolchain
- Python 3.11+ (pin tested versions in CI); FFmpeg + FFprobe with libx264 and AAC, plus filters/decoders required by each approved renderer; JSON Schema/Pydantic as checked in; pytest and approved quality tools. React/WaveSurfer/Node dependencies begin with WU4 frontend work. Do not install Streamlit.
- Keep Python dependency versions locked (e.g. generated constraints/lockfile); provide `pyproject.toml` with runtime/dev extras. Add frontend package-lock.json only if needed. No Docker or .NET requirement.
- The historical plan proposed `scripts/doctor.py`, but no such script is currently shipped. Use the existing `MediaToolchain` capability checks; WU3A may add a supported diagnostic interface only if it is included in the approved plan. Do not rely on hard-coded `C:\...` paths.

## Historical bootstrap command shape
The following block records the original environment target, not a guarantee that every command is currently implemented. Use checked-in backend packaging and current test commands. The obsolete `wrld_video` validation placeholder is intentionally removed; WU3A Phase 1 must approve the real headless command.
```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e '.[test]'
python -m pytest -m 'not media and not browser' -q
python -m pytest -m media -q
ruff check .
```
Linux/macOS: create venv with `python3`, activate with `source .venv/bin/activate`, otherwise use the same backend commands. WU4 documents the React development command when its frontend is implemented.

## WU3A delivery addition

WU3A must add and document the approved ordinary-PowerShell album/track export command. Doc 38 Decision 6 locks `python -m wrld_video_studio video-export --album-project ... --target album|track --profile youtube-1080p30-v1`, with `--track-id` for track targets and paired optional tool-path overrides. It must use the existing `.venv` and application use case, publish beneath `<album-project>/output/`, and never require React/FastAPI or shell out through an independent render script. The command must work independently of repository location and must not assume a drive, Windows username, library root, channel, or album name. Final handoff records the exact command actually used for the *Echoes of Asia* render, output layout, tool versions, automated results, and human playback result.

## Documentation / delivery rules
- Document all setup commands, known FFmpeg requirements, sample manifest, example render, troubleshooting, supported Windows paths, and cancellation behavior.
- Do not modify or delete canonical album metadata or source WAVs. Do not auto-upload to YouTube. Preserve legacy reference implementation unchanged unless user explicitly approves changes.
- Every work unit handoff reports changed files, actual commands run, passing/failing/skipped tests, measured timings if relevant, and unresolved issues. Stop and request approval before proceeding.

## v1.2 deployment scope, corrected
A local Python headless interface is required by WU3A; React plus a thin loopback FastAPI adapter is the later product UI. No Docker, broker, database, cloud environment, or Streamlit app is required. The application core remains independent of interface and deployment environment.
