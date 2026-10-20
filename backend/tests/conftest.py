import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "contracts" / "schemas"
FIXTURE_DIR = Path(__file__).parent / "contracts" / "fixtures"


@pytest.fixture
def schema_dir():
    return SCHEMA_DIR


@pytest.fixture
def manifest_schema(schema_dir):
    return schema_dir / "manifest-v2.schema.json"


@pytest.fixture
def override_schema(schema_dir):
    return schema_dir / "override-store-v1.schema.json"


@pytest.fixture
def valid_manifest():
    return json.loads((FIXTURE_DIR / "manifest-valid.json").read_text(encoding="utf-8"))
