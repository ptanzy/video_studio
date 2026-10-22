import ast
from pathlib import Path


def test_domain_and_application_sources_do_not_import_infrastructure_or_frameworks():
    source_root = Path(__file__).resolve().parents[2] / "src" / "wrld_video_studio"
    forbidden_roots = {"fastapi", "ffmpeg", "subprocess", "wrld_video_studio.infrastructure"}
    for layer in ("domain", "application"):
        for source_path in (source_root / layer).rglob("*.py"):
            tree = ast.parse(source_path.read_text(encoding="utf-8"))
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module)
            assert not any(
                name == forbidden or name.startswith(f"{forbidden}.")
                for name in imported
                for forbidden in forbidden_roots
            ), source_path


def test_artwork_source_port_and_use_case_do_not_depend_on_filesystem_adapter():
    source_root = Path(__file__).resolve().parents[2] / "src" / "wrld_video_studio"
    for relative_path in (
        Path("application/ports/artwork_sources.py"),
        Path("application/artwork_sources.py"),
    ):
        source = (source_root / relative_path).read_text(encoding="utf-8")
        assert "wrld_video_studio.infrastructure" not in source
