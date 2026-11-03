from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from wrld_video_studio.domain.wu4 import API_ERROR_VERSION, WU4Error
from wrld_video_studio.interfaces.http.wu4_models import ExportMetadataModel, ExportPreviewModel, InitializeMetadataModel, ReconcileMetadataModel, ReconcilePreviewModel, RegisterProjectModel, RelinkAssetModel, RelinkProjectModel, SaveEditorStateModel, SaveProjectDocumentModel, StartScanModel, ValidateMetadataModel


WU4_HTTP_STATUS = {
    "PROJECT_NOT_FOUND": 404, "PROJECT_REMOVED": 404, "PROJECT_ROOT_NOT_FOUND": 404,
    "RESOURCE_NOT_FOUND": 404, "TRACK_NOT_FOUND": 404, "EDITOR_STATE_NOT_FOUND": 404,
    "PROJECT_ALREADY_REGISTERED": 409, "PROJECT_RELINK_REQUIRED": 409,
    "PROJECT_IDENTITY_MISMATCH": 409, "REVISION_CONFLICT": 409, "SOURCE_CHANGED": 409,
    "COMMIT_INDETERMINATE": 500, "STORAGE_ERROR": 500, "PROJECT_UNAVAILABLE": 503,
    "MEDIA_PROBE_REQUIRED": 503, "SHORT_REVIEW_REQUIRED": 422,
    "PROJECT_PATH_INVALID": 422, "EDITOR_STATE_INVALID": 422,
    "REQUEST_INVALID": 422, "RANGE_NOT_SATISFIABLE": 416,
    "ASSET_NOT_FOUND": 404, "SCAN_NOT_FOUND": 404,
    "SCAN_CAPACITY_EXCEEDED": 429, "SCAN_CANCELLED": 409,
    "SCAN_ENTRY_LIMIT_EXCEEDED": 422, "SCAN_DEPTH_LIMIT_EXCEEDED": 422,
    "SCAN_WALL_TIME_EXCEEDED": 422, "ASSET_CAPABILITY_UNAVAILABLE": 422,
    "THUMBNAIL_VARIANT_INVALID": 422, "THUMBNAIL_INVALID": 422,
    "ASSET_RELINK_INVALID": 409, "PROJECT_BOUNDARY_OVERLAP": 409,
    "ASSET_CHANGED_DURING_VERIFICATION": 409,
    "ASSET_ID_COLLISION": 409,
    "PROJECT_DOCUMENT_NOT_FOUND": 404, "PROJECT_DOCUMENT_INVALID": 422,
    "PROJECT_PREFERENCES_INVALID": 422, "CREATION_STATE_INVALID": 422,
    "ANALYZER_UNAVAILABLE": 422,
    "METADATA_STATE_NOT_FOUND": 404, "METADATA_TARGET_NOT_FOUND": 404,
    "CREATION_UPGRADE_REQUIRED": 409, "METADATA_ALREADY_INITIALIZED": 409,
    "METADATA_RECONCILE_STALE": 409, "METADATA_EXPORT_PREVIEW_STALE": 409,
    "METADATA_EXPORT_EXISTS": 409, "METADATA_EXPORT_CHANGED": 409,
    "METADATA_EXPORT_OWNERSHIP_UNKNOWN": 409,
    "METADATA_STATE_INVALID": 422, "METADATA_VALIDATION_FAILED": 422,
    "METADATA_APPROVAL_INVALID": 422, "METADATA_EXPORT_SELECTION_INVALID": 422,
}


def error_response(error: WU4Error) -> JSONResponse:
    headers = None
    if error.code == "RANGE_NOT_SATISFIABLE" and type(error.details.get("size")) is int:
        headers = {"Content-Range": f"bytes */{error.details['size']}"}
    return JSONResponse(status_code=WU4_HTTP_STATUS.get(error.code, 422), headers=headers, content={"contract_version": API_ERROR_VERSION, "error": {"code": error.code, "message": error.message, "details": error.details}})


router = APIRouter(prefix="/api/v1", tags=["import-review"])


def _runtime(request: Request):
    runtime = getattr(request.app.state, "wu4_runtime", None)
    if runtime is None: raise WU4Error("PROJECT_UNAVAILABLE", "The Import and Review backend is not configured.")
    return runtime


@router.get("/project-roots")
def roots(request: Request): return _runtime(request).catalogs.roots()


@router.get("/project-roots/{root_id}/directories")
def directories(root_id: str, request: Request, parent: str = Query(default="")): return _runtime(request).catalogs.directories(root_id, parent)


@router.get("/projects")
def projects(request: Request): return _runtime(request).catalogs.list()


@router.post("/projects", status_code=201)
def register(payload: RegisterProjectModel, request: Request): return _runtime(request).catalogs.register(payload.root_id, payload.relative_path)


@router.put("/projects/{project_id}/location")
def relink(project_id: str, payload: RelinkProjectModel, request: Request): return _runtime(request).catalogs.relink(project_id, payload.root_id, payload.relative_path)


@router.delete("/projects/{project_id}", status_code=204)
def remove(project_id: str, request: Request): _runtime(request).catalogs.remove(project_id); return Response(status_code=204)


@router.get("/projects/{project_id}/album")
def album(project_id: str, request: Request): return _runtime(request).albums.read(project_id)


@router.post("/projects/{project_id}/validation")
def validation(project_id: str, request: Request): return _runtime(request).albums.validate(project_id)


@router.get("/projects/{project_id}/editor-state")
def editor_state(project_id: str, request: Request): return _runtime(request).editors.get(project_id)


@router.put("/projects/{project_id}/editor-state")
def save_editor_state(project_id: str, payload: SaveEditorStateModel, request: Request): return _runtime(request).editors.put(project_id, payload.expected_revision, payload.save_id, payload.state)


@router.get("/projects/{project_id}/preferences")
def project_preferences(project_id: str, request: Request):
    return _runtime(request).preferences.get(project_id)


@router.put("/projects/{project_id}/preferences")
def save_project_preferences(project_id: str, payload: SaveProjectDocumentModel, request: Request):
    return _runtime(request).preferences.put(project_id, payload.expected_revision, payload.save_id, payload.state)


@router.get("/projects/{project_id}/creation-state")
def creation_state(project_id: str, request: Request):
    return _runtime(request).creation.get(project_id)


@router.put("/projects/{project_id}/creation-state")
def save_creation_state(project_id: str, payload: SaveProjectDocumentModel, request: Request):
    return _runtime(request).creation.put(project_id, payload.expected_revision, payload.save_id, payload.state)


@router.get("/projects/{project_id}/youtube-metadata")
def youtube_metadata(project_id: str, request: Request):
    return _runtime(request).youtube_metadata.get(project_id)


@router.post("/projects/{project_id}/youtube-metadata/initialize", status_code=201)
def initialize_youtube_metadata(project_id: str, payload: InitializeMetadataModel, request: Request):
    return _runtime(request).youtube_metadata.initialize(project_id, payload.save_id, payload.creation_revision, payload.creation_state_digest)


@router.put("/projects/{project_id}/youtube-metadata")
def save_youtube_metadata(project_id: str, payload: SaveProjectDocumentModel, request: Request):
    return _runtime(request).youtube_metadata.put(project_id, payload.expected_revision, payload.save_id, payload.state)


@router.post("/projects/{project_id}/youtube-metadata/validate")
def validate_youtube_metadata(project_id: str, payload: ValidateMetadataModel, request: Request):
    return _runtime(request).youtube_metadata.validate(project_id, payload.state, payload.mode, payload.target_keys)


@router.post("/projects/{project_id}/youtube-metadata/reconcile-preview")
def preview_youtube_metadata_reconcile(project_id: str, payload: ReconcilePreviewModel, request: Request):
    return _runtime(request).youtube_metadata.reconcile_preview(project_id, payload.expected_revision, [item.model_dump() for item in payload.refresh_fields], [item.model_dump() for item in payload.carry_chapter_labels])


@router.post("/projects/{project_id}/youtube-metadata/reconcile")
def reconcile_youtube_metadata(project_id: str, payload: ReconcileMetadataModel, request: Request):
    return _runtime(request).youtube_metadata.reconcile(project_id, payload.expected_revision, payload.save_id, payload.preview_fingerprint, [item.model_dump() for item in payload.refresh_fields], [item.model_dump() for item in payload.carry_chapter_labels])


@router.post("/projects/{project_id}/youtube-metadata/export-preview")
def preview_youtube_metadata_export(project_id: str, payload: ExportPreviewModel, request: Request):
    return _runtime(request).youtube_metadata.export_preview(project_id, payload.expected_revision, payload.target_keys)


@router.post("/projects/{project_id}/youtube-metadata/exports")
def export_youtube_metadata(project_id: str, payload: ExportMetadataModel, request: Request):
    return _runtime(request).youtube_metadata.export(project_id, payload.expected_revision, payload.target_keys, payload.preview_fingerprint, payload.replace_existing, payload.expected_existing_sha256)


@router.get("/projects/{project_id}/inventory")
def inventory(project_id: str, request: Request):
    return _runtime(request).inventories.read(project_id)


@router.put("/projects/{project_id}/assets/{asset_id}/location")
def relink_asset(project_id: str, asset_id: str, payload: RelinkAssetModel, request: Request):
    return _runtime(request).inventories.relink(project_id, asset_id, payload.relative_path)


@router.post("/projects/{project_id}/inventory-scans", status_code=202)
def start_scan(project_id: str, payload: StartScanModel, request: Request):
    return _runtime(request).scans.start(project_id, payload.retry_of_scan_id)


@router.get("/projects/{project_id}/inventory-scans/{scan_id}")
def scan_status(project_id: str, scan_id: str, request: Request):
    return _runtime(request).scans.get(project_id, scan_id)


@router.delete("/projects/{project_id}/inventory-scans/{scan_id}", status_code=202)
def cancel_scan(project_id: str, scan_id: str, request: Request):
    return _runtime(request).scans.cancel(project_id, scan_id)


def _range(value: str | None, size: int) -> tuple[int, int] | None:
    if value is None: return None
    if not value.startswith("bytes=") or "," in value: raise WU4Error("RANGE_NOT_SATISFIABLE", "Only one byte range is supported.", {"size": size})
    spec = value[6:]
    try:
        left, right = spec.split("-", 1)
        if left:
            start = int(left); end = min(int(right), size - 1) if right else size - 1
        else:
            length = int(right); start = max(0, size - length); end = size - 1
    except (ValueError, TypeError):
        raise WU4Error("RANGE_NOT_SATISFIABLE", "The byte range is invalid.", {"size": size}) from None
    if start < 0 or start >= size or end < start: raise WU4Error("RANGE_NOT_SATISFIABLE", "The byte range is outside the resource.", {"size": size})
    return start, end


@router.get("/projects/{project_id}/tracks/{track_id}/audio")
def audio(project_id: str, track_id: str, request: Request):
    return _audio(project_id, track_id, request, head=False)


@router.head("/projects/{project_id}/tracks/{track_id}/audio", include_in_schema=False)
def audio_head(project_id: str, track_id: str, request: Request):
    return _audio(project_id, track_id, request, head=True)


def _audio(project_id: str, track_id: str, request: Request, *, head: bool):
    resource, metadata = _runtime(request).albums.open_audio(project_id, track_id)
    size, etag = metadata["size"], metadata["etag"]
    if request.headers.get("if-none-match") == etag and "range" not in request.headers:
        resource.close(); return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "private, must-revalidate"})
    try:
        range_header = request.headers.get("range")
        if range_header is not None and request.headers.get("if-range") not in (None, etag):
            range_header = None
        selected = _range(range_header, size)
    except BaseException:
        resource.close()
        raise
    if selected is None: start, end, status = 0, size - 1, 200
    else: start, end, status = selected[0], selected[1], 206
    headers = {"Accept-Ranges": "bytes", "Content-Length": str(end - start + 1), "Content-Type": "audio/wav", "ETag": etag, "Cache-Control": "private, must-revalidate"}
    if status == 206: headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    if head: resource.close(); return Response(status_code=status, headers=headers)
    resource.seek(start)
    def stream() -> Iterator[bytes]:
        remaining = end - start + 1
        try:
            while remaining:
                chunk = resource.read(min(64 * 1024, remaining))
                if not chunk: break
                remaining -= len(chunk); yield chunk
        finally: resource.close()
    return StreamingResponse(stream(), status_code=status, headers=headers, media_type="audio/wav")


@router.get("/projects/{project_id}/assets/{asset_id}/audio")
def asset_audio(project_id: str, asset_id: str, request: Request):
    resource, metadata = _runtime(request).assets.open_audio(project_id, asset_id)
    return _stream_resource(resource, metadata, request, head=False)


@router.head("/projects/{project_id}/assets/{asset_id}/audio", include_in_schema=False)
def asset_audio_head(project_id: str, asset_id: str, request: Request):
    resource, metadata = _runtime(request).assets.open_audio(project_id, asset_id)
    return _stream_resource(resource, metadata, request, head=True)


@router.get("/projects/{project_id}/assets/{asset_id}/image")
def asset_image(project_id: str, asset_id: str, request: Request):
    resource, metadata = _runtime(request).assets.open_image(project_id, asset_id)
    return _stream_resource(resource, metadata, request, head=False)


@router.head("/projects/{project_id}/assets/{asset_id}/image", include_in_schema=False)
def asset_image_head(project_id: str, asset_id: str, request: Request):
    resource, metadata = _runtime(request).assets.open_image(project_id, asset_id)
    return _stream_resource(resource, metadata, request, head=True)


@router.get("/projects/{project_id}/assets/{asset_id}/thumbnails/{variant}")
def asset_thumbnail(project_id: str, asset_id: str, variant: str, request: Request):
    data, etag = _runtime(request).assets.thumbnail(project_id, asset_id, variant)
    headers = {"ETag": etag, "Cache-Control": "private, must-revalidate", "X-Content-Type-Options": "nosniff"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=data, media_type="image/png", headers=headers)


def _stream_resource(resource, metadata: dict, request: Request, *, head: bool):
    size, etag, content_type = metadata["size"], metadata["etag"], metadata["content_type"]
    common = {"ETag": etag, "Cache-Control": "private, must-revalidate", "X-Content-Type-Options": "nosniff"}
    if request.headers.get("if-none-match") == etag and "range" not in request.headers:
        resource.close()
        return Response(status_code=304, headers=common)
    try:
        range_header = request.headers.get("range")
        if range_header is not None and request.headers.get("if-range") not in (None, etag):
            range_header = None
        selected = _range(range_header, size)
    except BaseException:
        resource.close()
        raise
    start, end, status = (0, size - 1, 200) if selected is None else (selected[0], selected[1], 206)
    headers = {**common, "Accept-Ranges": "bytes", "Content-Length": str(end - start + 1), "Content-Type": content_type}
    if status == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    if head:
        resource.close()
        return Response(status_code=status, headers=headers)
    resource.seek(start)
    def stream() -> Iterator[bytes]:
        remaining = end - start + 1
        try:
            while remaining:
                chunk = resource.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk
        finally:
            resource.close()
    return StreamingResponse(stream(), status_code=status, headers=headers, media_type=content_type)


__all__ = ["error_response", "router"]
