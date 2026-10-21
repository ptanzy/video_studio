import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from wrld_video_studio.domain.errors import IndeterminateCommitError, StudioError
from wrld_video_studio.infrastructure.override_store import OverrideStore


ALBUM_ID = "WRLD-FI-S01-A08"
LOCK_STRESS_ITERATIONS = int(os.environ.get("WU1_LOCK_STRESS_ITERATIONS", "1"))


def test_create_read_update_reload_and_compare_and_swap(tmp_path, override_schema):
    store = OverrideStore(tmp_path, override_schema)
    initial = store.create(ALBUM_ID)
    assert initial["revision"] == 0
    assert store.read(ALBUM_ID) == initial

    updated = store.update(ALBUM_ID, 0, {"opaque": {"value": "preserve"}})
    assert updated["revision"] == 1
    assert OverrideStore(tmp_path, override_schema).read(ALBUM_ID) == updated

    with pytest.raises(StudioError) as caught:
        store.update(ALBUM_ID, 0, {"ignored": True})
    assert caught.value.code == "REVISION_CONFLICT"
    assert store.read(ALBUM_ID) == updated


def test_two_sequential_updates_with_same_revision_have_one_winner(tmp_path, override_schema):
    store = OverrideStore(tmp_path, override_schema)
    store.create(ALBUM_ID)
    store.update(ALBUM_ID, 0, {"winner": 1})
    with pytest.raises(StudioError) as caught:
        store.update(ALBUM_ID, 0, {"winner": 2})
    assert caught.value.code == "REVISION_CONFLICT"


def test_replace_failure_preserves_previous_store_and_cleans_temp_file(tmp_path, override_schema):
    store = OverrideStore(tmp_path, override_schema)
    store.create(ALBUM_ID)
    before = store.read(ALBUM_ID)

    def fail_replace(source, destination):
        raise OSError("injected replace failure")

    failing_store = OverrideStore(tmp_path, override_schema, replace=fail_replace)
    with pytest.raises(StudioError) as caught:
        failing_store.update(ALBUM_ID, 0, {"new": "value"})

    assert caught.value.code == "STORAGE_ERROR"
    assert store.read(ALBUM_ID) == before
    assert not list(tmp_path.glob("*.tmp"))
    assert not list(tmp_path.glob(".*.tmp"))


def test_create_failure_leaves_no_partial_store(tmp_path, override_schema):
    def fail_replace(source, destination):
        raise OSError("injected replace failure")

    store = OverrideStore(tmp_path, override_schema, replace=fail_replace)
    with pytest.raises(StudioError) as caught:
        store.create(ALBUM_ID)
    assert caught.value.code == "STORAGE_ERROR"
    assert not list(tmp_path.glob("*.json"))


@pytest.mark.parametrize("stress_iteration", range(LOCK_STRESS_ITERATIONS))
def test_existing_lock_prevents_another_writer(tmp_path, override_schema, stress_iteration):
    store = OverrideStore(tmp_path, override_schema)
    store.create(ALBUM_ID)
    acquired = threading.Event()
    release = threading.Event()

    def hold_lock():
        with store._writer_lock(ALBUM_ID):
            acquired.set()
            release.wait(timeout=10)

    holder = threading.Thread(target=hold_lock)
    holder.start()
    try:
        assert acquired.wait(timeout=10)
        with pytest.raises(StudioError) as caught:
            store.update(ALBUM_ID, 0, {"value": True})
        assert caught.value.code == "STORAGE_ERROR"
    finally:
        release.set()
        holder.join(timeout=10)
    assert store.read(ALBUM_ID)["revision"] == 0


@pytest.mark.parametrize("stress_iteration", range(LOCK_STRESS_ITERATIONS))
def test_process_death_releases_writer_lock(tmp_path, override_schema, stress_iteration):
    store = OverrideStore(tmp_path, override_schema)
    store.create(ALBUM_ID)
    mutex_name = (
        f"Local\\WRLDVideoStudio-{store._lock_key(ALBUM_ID)}"
        if os.name == "nt"
        else str(store._lock_path(ALBUM_ID).resolve())
    )
    script = (
        "import json, os, sys, threading; "
        + ("import pywin32_bootstrap; " if os.name == "nt" else "")
        + "from wrld_video_studio.infrastructure.override_store import OverrideStore; "
        "store = OverrideStore(sys.argv[1], sys.argv[2]); "
        "lock = store._writer_lock(sys.argv[3]); "
        "owner = lock.__enter__(); "
        "print(json.dumps({'event':'acquired','pid':os.getpid(),'thread_id':threading.get_native_id(),'lock':owner}), flush=True); "
        "sys.stdin.readline()"
    )
    child_executable = getattr(sys, "_base_executable", sys.executable)
    child_environment = os.environ.copy()
    child_environment["PYTHONPATH"] = os.pathsep.join(sys.path)
    pywin32_dlls = str(Path(sys.prefix) / "Lib" / "site-packages" / "pywin32_system32")
    if os.name == "nt" and os.path.isdir(pywin32_dlls):
        child_environment["PATH"] = pywin32_dlls + os.pathsep + child_environment.get("PATH", "")
    process = subprocess.Popen(
        [child_executable, "-c", script, str(tmp_path), str(override_schema), ALBUM_ID],
        env=child_environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    child_info = None
    parent_info = {
        "pid": os.getpid(),
        "thread_id": threading.get_native_id(),
        "mutex_name": mutex_name,
        "root": str(store.root.resolve()),
        "album_id": ALBUM_ID,
        "child_executable": child_executable,
        "launcher_pid": process.pid,
    }
    try:
        assert process.stdout is not None
        line = process.stdout.readline()
        if not line:
            child_error = process.stderr.read() if process.stderr else ""
            pytest.fail(
                f"child exited before lock acquisition; parent={parent_info}; "
                f"returncode={process.poll()}; stderr={child_error}"
            )
        child_info = json.loads(line)
        assert child_info["event"] == "acquired", f"child did not report lock acquisition: {child_info}"
        assert child_info["pid"] == process.pid, f"child PID mismatch: {child_info}; parent={parent_info}"
        assert child_info["pid"] != os.getpid(), f"owner is not a child process: {child_info}; parent={parent_info}"
        assert child_info["thread_id"] > 0
        assert child_info["lock"]["process_id"] == process.pid
        assert child_info["lock"]["thread_id"] == child_info["thread_id"]
        assert child_info["lock"]["mutex_name"] == mutex_name
        valid_results = {"WAIT_OBJECT_0", "WAIT_ABANDONED"} if os.name == "nt" else {"LOCK_ACQUIRED"}
        assert child_info["lock"]["wait_result"] in valid_results
        process.kill()
        child_exit = process.wait(timeout=10)
        assert process.poll() is not None, f"child did not fully exit: {parent_info}; child={child_info}"
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        if process.stdin:
            process.stdin.close()
        if process.stdout:
            process.stdout.close()
        if process.stderr:
            process.stderr.close()

    assert process.returncode is not None, f"child termination unconfirmed: {parent_info}; child={child_info}"
    assert child_exit != 0, f"child did not report forced termination: {parent_info}; child={child_info}"
    with store._writer_lock(ALBUM_ID) as recovered_lock:
        parent_info["recovery_wait_result"] = recovered_lock["wait_result"]
        valid_recovery_results = (
            {"WAIT_ABANDONED", "WAIT_OBJECT_0"}
            if os.name == "nt"
            else {"LOCK_ACQUIRED"}
        )
        assert recovered_lock["process_id"] == os.getpid(), (
            f"recovery lock PID mismatch: {parent_info}; child={child_info}"
        )
        assert recovered_lock["thread_id"] == threading.get_native_id(), (
            f"recovery lock thread mismatch: {parent_info}; child={child_info}"
        )
        assert recovered_lock["mutex_name"] == mutex_name, (
            f"recovery lock identity mismatch: {parent_info}; child={child_info}"
        )
        assert recovered_lock["wait_result"] in valid_recovery_results, (
            f"unexpected post-crash lock result: {parent_info}; child={child_info}"
        )
    try:
        updated = store.update(ALBUM_ID, 0, {"after_crash": True})
    except StudioError as error:
        pytest.fail(
            f"writer lock remained unavailable after child exit; parent={parent_info}; "
            f"child={child_info}; child_returncode={process.returncode}; error={error.to_dict()}"
        )
    assert updated["revision"] == 1


@pytest.mark.parametrize(
    "invalid_value",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
        {1: "integer key"},
        {"nested": ("tuple",)},
        {"nested": {"set"}},
        {"nested": object()},
        "lone surrogate: \ud800",
    ],
    ids=["nan", "positive-infinity", "negative-infinity", "non-string-key", "tuple", "set", "object", "surrogate"],
)
def test_invalid_json_values_are_rejected_without_advancing_revision(
    tmp_path, override_schema, invalid_value
):
    store = OverrideStore(tmp_path, override_schema)
    store.create(ALBUM_ID)
    before = store.read(ALBUM_ID)

    with pytest.raises(StudioError) as caught:
        store.update(ALBUM_ID, 0, {"invalid": invalid_value})

    assert caught.value.code == "STORAGE_ERROR"
    assert store.read(ALBUM_ID) == before


def test_json_round_trip_preserves_supported_values(tmp_path, override_schema):
    store = OverrideStore(tmp_path, override_schema)
    store.create(ALBUM_ID)
    overrides = {"text": "café", "number": 1.25, "negative_zero": -0.0, "nested": [None, True]}

    saved = store.update(ALBUM_ID, 0, overrides)

    assert store.read(ALBUM_ID) == saved


def test_failure_after_replace_reports_indeterminate_commit(tmp_path, override_schema):
    def fail_directory_sync(_directory):
        raise OSError("injected directory sync failure")

    store = OverrideStore(tmp_path, override_schema)
    store.create(ALBUM_ID)
    failing_store = OverrideStore(
        tmp_path, override_schema, sync_directory=fail_directory_sync
    )

    with pytest.raises(IndeterminateCommitError) as caught:
        failing_store.update(ALBUM_ID, 0, {"new": "value"})

    assert caught.value.code == "STORAGE_ERROR"
    assert caught.value.details["commit_state"] == "indeterminate"
    assert store.read(ALBUM_ID)["revision"] == 1


def test_source_files_are_unchanged_by_store_operations(tmp_path, override_schema):
    source = tmp_path / "source.wav"
    source.write_bytes(b"source media fixture")
    original = source.read_bytes()

    store = OverrideStore(tmp_path / "state", override_schema)
    store.create(ALBUM_ID)
    store.update(ALBUM_ID, 0, {"notes": "approved fixture data"})

    assert source.read_bytes() == original
