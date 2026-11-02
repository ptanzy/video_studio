from __future__ import annotations

import json
import os
import tempfile
import stat
from pathlib import Path
from typing import Any, Mapping

import portalocker
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource

from wrld_video_studio.domain.canonical_json import canonical_json_bytes
from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.domain.video_export import RENDER_REPORT_VERSION


class JsonVideoResultStore:
    def __init__(
        self,
        root: str | Path,
        schema_path: str | Path | tuple[str | Path, ...] | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.validators: dict[str, Draft202012Validator] = {}
        if schema_path is not None:
            paths = (
                tuple(Path(item) for item in schema_path)
                if isinstance(schema_path, tuple)
                else (Path(schema_path),)
            )
            resources = []
            for path in paths[0].parent.glob("*.schema.json"):
                document = json.loads(path.read_text(encoding="utf-8"))
                if "$id" in document:
                    resources.append((document["$id"], Resource.from_contents(document)))
            registry = Registry().with_resources(resources)
            for path in paths:
                schema = json.loads(path.read_text(encoding="utf-8"))
                version = schema["properties"]["contract_version"]["const"]
                self.validators[version] = Draft202012Validator(
                    schema,
                    registry=registry,
                    format_checker=FormatChecker(),
                )

    def save(self, job_id: str, attempt_id: str, result: Mapping[str, Any]) -> None:
        if self.validators:
            validator = self.validators.get(result.get("contract_version"))
            if validator is None:
                raise MediaInfrastructureError(
                    "RESULT_INVALID", "Generated export result violates its contract."
                )
            errors = sorted(validator.iter_errors(dict(result)), key=lambda item: list(item.path))
            if errors:
                raise MediaInfrastructureError(
                    "RESULT_INVALID", "Generated export result violates its contract."
                )
        self._write(self._path(job_id, attempt_id), dict(result))

    def load(self, job_id: str, attempt_id: str) -> dict[str, Any] | None:
        path = self._path(job_id, attempt_id)
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise MediaInfrastructureError("STORAGE_ERROR", "Private export result is invalid.") from error
        if not isinstance(value, dict):
            raise MediaInfrastructureError("STORAGE_ERROR", "Private export result is invalid.")
        if self.validators:
            validator = self.validators.get(value.get("contract_version"))
            if validator is None or not validator.is_valid(value):
                raise MediaInfrastructureError(
                    "STORAGE_ERROR", "Private export result is invalid."
                )
        return value

    def save_report_base_revision(self, job_id: str, attempt_id: str, revision: int) -> None:
        if type(revision) is not int or revision < -1:
            raise MediaInfrastructureError("STORAGE_ERROR", "Report base revision is invalid.")
        self._write(self._revision_path(job_id, attempt_id), {"revision": revision})

    def load_report_base_revision(self, job_id: str, attempt_id: str) -> int:
        path = self._revision_path(job_id, attempt_id)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            revision = value["revision"]
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
            raise MediaInfrastructureError(
                "STORAGE_ERROR", "Private report revision record is unavailable."
            ) from error
        if type(revision) is not int or revision < -1:
            raise MediaInfrastructureError("STORAGE_ERROR", "Private report revision is invalid.")
        return revision

    def _path(self, job_id: str, attempt_id: str) -> Path:
        import hashlib

        job = hashlib.sha256(job_id.encode()).hexdigest()
        attempt = hashlib.sha256(attempt_id.encode()).hexdigest()
        return self.root / job / f"{attempt}.json"

    def _revision_path(self, job_id: str, attempt_id: str) -> Path:
        result = self._path(job_id, attempt_id)
        return result.with_suffix(".report-revision.json")

    @staticmethod
    def _write(path: Path, value: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as stream:
                temporary = stream.name
                stream.write(canonical_json_bytes(dict(value)))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            temporary = None
        except OSError as error:
            raise MediaInfrastructureError("STORAGE_ERROR", "Could not persist export result.") from error
        finally:
            if temporary:
                Path(temporary).unlink(missing_ok=True)


class RenderReportStore:
    def __init__(self, project_root: str | Path, schema_path: str | Path) -> None:
        self.project_root = Path(project_root).resolve()
        self.path = self.project_root / "output" / "metadata" / "render_report.json"
        self.lock_path = self.project_root / "output" / ".render-report.lock"
        schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
        self.validator = Draft202012Validator(schema, format_checker=FormatChecker())

    def matching_result(self, request_digest: str) -> dict[str, Any] | None:
        report = self._read()
        if report is None:
            return None
        for item in reversed(report["history"]):
            result = item.get("result") if isinstance(item, dict) else None
            if isinstance(result, dict) and result.get("request_digest") == request_digest:
                return result
        return None

    def current_revision(self) -> int:
        report = self._read()
        return -1 if report is None else int(report["revision"])

    def has_artifact(self, artifact: Mapping[str, Any]) -> bool:
        report = self._read()
        if report is None:
            return False
        return any(item == artifact for item in report["artifacts"])

    def publish(
        self,
        project_id: str,
        result: Mapping[str, Any],
        *,
        renderer_version: str | None = None,
        input_fingerprints: list[dict[str, str]] | None = None,
        toolchain: Mapping[str, Any] | None = None,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        self._assert_safe(self.path, allow_missing=True)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._assert_safe(self.path, allow_missing=True)
        self._assert_safe(self.lock_path, allow_missing=True)
        try:
            with portalocker.Lock(str(self.lock_path), mode="a", timeout=0):
                existing = self._read()
                if existing is None:
                    report: dict[str, Any] = {
                        "schema_version": RENDER_REPORT_VERSION,
                        "project_id": project_id,
                        "revision": 0,
                        "artifacts": [],
                        "history": [],
                        "updated_at": result["finished_at"],
                    }
                else:
                    report = existing
                    if report["project_id"] != project_id:
                        raise MediaInfrastructureError(
                            "REPORT_CONFLICT", "Render report belongs to another project identity."
                        )
                    for history in report["history"]:
                        previous = history.get("result") if isinstance(history, dict) else None
                        if isinstance(previous, dict) and previous.get("request_digest") == result.get("request_digest"):
                            return report
                    if expected_revision is not None and report["revision"] != expected_revision:
                        raise MediaInfrastructureError(
                            "REPORT_CONFLICT", "Render report changed after the job snapshot was created."
                        )
                    report["revision"] += 1
                if existing is None and expected_revision not in {None, -1}:
                    raise MediaInfrastructureError(
                        "REPORT_CONFLICT", "Render report revision does not match the job snapshot."
                    )
                by_path = {
                    item["path"]: item for item in report["artifacts"]
                    if isinstance(item, dict) and isinstance(item.get("path"), str)
                }
                for artifact in result["artifacts"]:
                    previous = by_path.get(artifact["path"])
                    if previous is not None and previous != artifact:
                        raise MediaInfrastructureError(
                            "OUTPUT_EXISTS", "Render report already catalogs different content at the output path."
                        )
                    by_path[artifact["path"]] = artifact
                report["artifacts"] = [by_path[key] for key in sorted(by_path)]
                history = {
                    "job_id": result["job_id"],
                    "attempt_id": result["attempt_id"],
                    "request_digest": result["request_digest"],
                    "result": dict(result),
                }
                if renderer_version is not None:
                    history["renderer_version"] = renderer_version
                if input_fingerprints is not None:
                    history["input_fingerprints"] = input_fingerprints
                if toolchain is not None:
                    history["toolchain"] = dict(toolchain)
                report["history"].append(history)
                report["updated_at"] = result["finished_at"]
                try:
                    self.validator.validate(report)
                except ValidationError as error:
                    raise MediaInfrastructureError(
                        "REPORT_INVALID", "Generated render report violates its contract."
                    ) from error
                JsonVideoResultStore._write(self.path, report)
                return report
        except portalocker.exceptions.LockException as error:
            raise MediaInfrastructureError("OUTPUT_BUSY", "Render report is being updated.") from error

    def _read(self) -> dict[str, Any] | None:
        self._assert_safe(self.path, allow_missing=True)
        if not self.path.exists():
            return None
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            self.validator.validate(value)
        except Exception as error:
            raise MediaInfrastructureError("REPORT_INVALID", "Existing render report is invalid.") from error
        if not isinstance(value, dict):
            raise MediaInfrastructureError("REPORT_INVALID", "Existing render report is invalid.")
        return value

    def _assert_safe(self, path: Path, *, allow_missing: bool) -> None:
        candidate = self.project_root
        try:
            path.relative_to(self.project_root)
        except ValueError as error:
            raise MediaInfrastructureError("INVALID_OUTPUT_PATH", "Report path escapes project.") from error
        for part in path.relative_to(self.project_root).parts:
            candidate = candidate / part
            if not candidate.exists():
                if allow_missing:
                    continue
                raise MediaInfrastructureError("INVALID_OUTPUT_PATH", "Report path is missing.")
            try:
                info = candidate.lstat()
            except OSError as error:
                raise MediaInfrastructureError("STORAGE_ERROR", "Report path is inaccessible.") from error
            attributes = getattr(info, "st_file_attributes", 0)
            if stat.S_ISLNK(info.st_mode) or attributes & getattr(
                stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400
            ):
                raise MediaInfrastructureError(
                    "INVALID_OUTPUT_PATH", "Report path may not traverse links or reparse points."
                )
