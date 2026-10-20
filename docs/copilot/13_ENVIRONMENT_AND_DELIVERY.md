# Reproducible environment and delivery — v1.1

## Toolchain
- Python 3.11+ (pin tested versions in CI); FFmpeg + FFprobe with libx264, AAC and libass/subtitles; Streamlit and Pillow; Pydantic or JSON Schema library; pytest, pytest-cov, ruff. WaveSurfer.js Regions plugin with a pinned version and Node LTS only when building its custom frontend in WU5.
- Keep Python dependency versions locked (e.g. generated constraints/lockfile); provide `pyproject.toml` with runtime/dev extras. Add frontend package-lock.json only if needed. No Docker or .NET requirement.
- `scripts/doctor.py` checks Python, FFmpeg/FFprobe binaries, filters/encoders, write permissions, supported versions, and returns actionable failures. Do not rely on hard-coded `C:\...` paths.

## Developer commands (target contract; implement in WU1)
```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
python scripts/doctor.py
python -m wrld_video validate manifest.proposed.example.json
python -m pytest -m 'not media and not browser' -q
python -m pytest -m media -q
ruff check .
```
Linux/macOS: create venv with `python3`, activate with `source .venv/bin/activate`, otherwise use the same commands. `streamlit run app.py` after WU4.

## Documentation / delivery rules
- Document all setup commands, known FFmpeg requirements, sample manifest, example render, troubleshooting, supported Windows paths, and cancellation behavior.
- Do not modify or delete canonical album metadata or source WAVs. Do not auto-upload to YouTube. Preserve legacy reference implementation unchanged unless user explicitly approves changes.
- Every work unit handoff reports changed files, actual commands run, passing/failing/skipped tests, measured timings if relevant, and unresolved issues. Stop and request approval before proceeding.

## v1.2 deployment scope
A local Python CLI and Streamlit app are the only required deployment interfaces. No Docker, HTTP service, broker, database, or cloud environment is required for the POC. The application core must remain independent of the interface and deployment environment.
