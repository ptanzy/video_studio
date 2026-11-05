from __future__ import annotations

import json

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


SCHEMAS = (
    "creation-render-common-v1.schema.json",
    "creation-render-request-v1.schema.json",
    "creation-render-plan-v1.schema.json",
    "creation-render-preflight-v1.schema.json",
    "creation-render-targets-v1.schema.json",
    "creation-render-job-v1.schema.json",
    "creation-render-result-v1.schema.json",
    "creation-render-recovery-request-v1.schema.json",
    "creation-render-recovery-preflight-v1.schema.json",
)


def _registry(schema_dir):
    all_documents = [(path.name, json.loads(path.read_text(encoding="utf-8"))) for path in schema_dir.glob("*.schema.json")]
    selected = [document for name, document in all_documents if name in SCHEMAS]
    resources = []
    for name, document in all_documents:
        resource = Resource.from_contents(document)
        if "$id" in document:
            resources.append((document["$id"], resource))
        resources.append((name, resource))
    return selected, Registry().with_resources(resources)


def test_wu6_schemas_and_examples_validate(schema_dir):
    documents, registry = _registry(schema_dir)
    for document in documents:
        Draft202012Validator.check_schema(document)
    validators = {document["$id"].rsplit("/", 1)[-1]: Draft202012Validator(document, registry=registry) for document in documents}
    example_dir = schema_dir.parents[1] / "examples" / "wu6"
    mapping = {
        "render-request-preflight.v1.example.json": "creation-render-request-v1.schema.json",
        "render-request-submit.v1.example.json": "creation-render-request-v1.schema.json",
        "album-render-plan.v1.example.json": "creation-render-plan-v1.schema.json",
        "single-render-plan.v1.example.json": "creation-render-plan-v1.schema.json",
        "short-render-plan.v1.example.json": "creation-render-plan-v1.schema.json",
        "preflight-blocked.v1.example.json": "creation-render-preflight-v1.schema.json",
        "job-running.v1.example.json": "creation-render-job-v1.schema.json",
        "render-result-succeeded.v1.example.json": "creation-render-result-v1.schema.json",
    }
    for example_name, schema_name in mapping.items():
        validators[schema_name].validate(json.loads((example_dir / example_name).read_text(encoding="utf-8")))
    common = validators["creation-render-common-v1.schema.json"]
    common.evolve(schema=common.schema["$defs"]["verifiedArtifact"]).validate(json.loads((example_dir / "artifact.v1.example.json").read_text(encoding="utf-8")))
    common.evolve(schema=common.schema["$defs"]["timeline"]).validate(json.loads((example_dir / "timeline.v1.example.json").read_text(encoding="utf-8")))


def test_wu6_timeline_examples_are_contiguous_and_exact(schema_dir):
    example_dir = schema_dir.parents[1] / "examples" / "wu6"
    for name in ("album-render-plan.v1.example.json", "single-render-plan.v1.example.json", "short-render-plan.v1.example.json"):
        timeline = json.loads((example_dir / name).read_text(encoding="utf-8"))["timeline"]
        cursor = 0
        for sequence, entry in enumerate(timeline["entries"], start=1):
            assert entry["sequence"] == sequence
            assert entry["output_start_sample"] == cursor
            assert entry["output_end_sample"] == cursor + entry["sample_count"]
            cursor = entry["output_end_sample"]
        assert cursor == timeline["total_samples"]
        assert timeline["duration_seconds"] == timeline["total_samples"] / 48_000
