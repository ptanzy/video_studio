from __future__ import annotations

import hashlib
import json
import math
from typing import Any


def canonical_json_bytes(value: Any) -> bytes:
    def validate(item: Any, path: str) -> None:
        if item is None or type(item) in (str, bool, int):
            if isinstance(item, str):
                item.encode("utf-8", errors="strict")
            return
        if type(item) is float:
            if not math.isfinite(item):
                raise ValueError(f"Non-finite number at {path}")
            return
        if type(item) is list:
            for index, child in enumerate(item):
                validate(child, f"{path}[{index}]")
            return
        if type(item) is dict:
            for key, child in item.items():
                if type(key) is not str:
                    raise ValueError(f"Non-string object key at {path}")
                key.encode("utf-8", errors="strict")
                validate(child, f"{path}.{key}")
            return
        raise ValueError(f"Unsupported JSON value at {path}: {type(item).__name__}")

    validate(value, "$" )
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8", errors="strict")
    decoded = json.loads(encoded, parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))
    if not _same_json_types(value, decoded):
        raise ValueError("Value changed during strict JSON round-trip")
    return encoded


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _same_json_types(original: Any, decoded: Any) -> bool:
    if type(original) is not type(decoded):
        return False
    if type(original) is dict:
        return original.keys() == decoded.keys() and all(
            _same_json_types(original[key], decoded[key]) for key in original
        )
    if type(original) is list:
        return len(original) == len(decoded) and all(
            _same_json_types(left, right) for left, right in zip(original, decoded)
        )
    return original == decoded