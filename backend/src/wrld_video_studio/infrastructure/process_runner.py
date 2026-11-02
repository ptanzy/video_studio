from __future__ import annotations

import os
import re
import signal
import subprocess
import threading
from pathlib import Path
from typing import Any

from wrld_video_studio.domain.jobs import ProcessExecution
from wrld_video_studio.domain.media_errors import MediaInfrastructureError


class _WindowsOwnershipFailure(RuntimeError):
    def __init__(
        self,
        stage: str,
        error: BaseException,
        *,
        process_exited: bool | None,
        already_in_job: bool | None,
    ) -> None:
        super().__init__(f"Windows process ownership failed during {stage}")
        self.stage = stage
        self.windows_error = _windows_error_code(error)
        self.process_exited = process_exited
        self.already_in_job = already_in_job


class _BoundedPipe:
    def __init__(self, stream: Any, limit: int, keep_tail: bool, on_data: Any = None) -> None:
        self.stream = stream
        self.limit = limit
        self.keep_tail = keep_tail
        self.on_data = on_data
        self.callback_error: BaseException | None = None
        self.data = bytearray()
        self.thread = threading.Thread(target=self._drain, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def _drain(self) -> None:
        reader = getattr(self.stream, "read1", self.stream.read)
        while True:
            chunk = reader(8192)
            if not chunk:
                break
            if self.on_data is not None:
                try:
                    self.on_data(chunk.decode("utf-8", errors="replace"))
                except BaseException as error:
                    self.callback_error = error
                    break
            if self.keep_tail:
                self.data.extend(chunk)
                if len(self.data) > self.limit:
                    del self.data[: len(self.data) - self.limit]
            elif len(self.data) < self.limit:
                self.data.extend(chunk[: self.limit - len(self.data)])

    def result(self, timeout: float) -> str:
        self.thread.join(timeout=max(0.0, timeout))
        if self.thread.is_alive():
            raise TimeoutError("process output pipe did not close")
        return bytes(self.data).decode("utf-8", errors="replace")

    def close(self) -> None:
        try:
            self.stream.close()
        except OSError:
            pass


class SubprocessRunner:
    def __init__(
        self,
        *,
        output_limit: int = 1_048_576,
        stderr_limit: int = 16_384,
        grace_seconds: float = 1.0,
        heartbeat_interval_seconds: float = 1.0,
    ) -> None:
        self.output_limit = output_limit
        self.stderr_limit = stderr_limit
        self.grace_seconds = grace_seconds
        self.heartbeat_interval_seconds = heartbeat_interval_seconds

    def run(
        self,
        argv: list[str],
        timeout_seconds: float,
        cancel_event: Any = None,
        heartbeat: Any = None,
        progress_callback: Any = None,
        working_directory: str | Path | None = None,
    ) -> ProcessExecution:
        if not argv or not all(isinstance(argument, str) for argument in argv):
            raise MediaInfrastructureError("INVALID_COMMAND", "Process arguments must be strings.")
        if timeout_seconds <= 0:
            raise MediaInfrastructureError("INVALID_TIMEOUT", "Process timeout must be positive.")
        kwargs: dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "shell": False,
            "close_fds": True,
        }
        if working_directory is not None:
            try:
                directory = Path(working_directory).resolve(strict=True)
            except OSError as error:
                raise MediaInfrastructureError(
                    "INVALID_COMMAND", "Process working directory is unavailable."
                ) from error
            if not directory.is_dir():
                raise MediaInfrastructureError(
                    "INVALID_COMMAND", "Process working directory must be a directory."
                )
            kwargs["cwd"] = str(directory)
        if os.name == "nt":
            import win32con

            # A child can otherwise exit between CreateProcess and Job Object
            # assignment.  Starting suspended makes ownership atomic from the
            # application's perspective: no child code runs before assignment.
            kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP | win32con.CREATE_SUSPENDED
            )
        else:
            kwargs["start_new_session"] = True
        try:
            process = subprocess.Popen(argv, **kwargs)
        except OSError as error:
            raise MediaInfrastructureError(
                "PROCESS_START_FAILED", "Could not start the requested media process."
            ) from error
        windows_job = None
        try:
            if os.name == "nt":
                windows_job = self._create_windows_job(process)
                self._resume_windows_process(process)
            else:
                windows_job = None
        except Exception as error:
            if windows_job is not None:
                self._close_windows_job(windows_job)
                windows_job = None
            else:
                self._taskkill_tree(process.pid)
            try:
                process.wait(timeout=max(self.grace_seconds, 1.0))
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.wait(timeout=max(self.grace_seconds, 0.05))
                except subprocess.TimeoutExpired as reap_error:
                    if process.stdout is not None:
                        process.stdout.close()
                    if process.stderr is not None:
                        process.stderr.close()
                    raise MediaInfrastructureError(
                        "PROCESS_REAP_FAILED", "Media process could not be reaped after ownership setup failed."
                    ) from reap_error
            raise MediaInfrastructureError(
                "PROCESS_OWNERSHIP_FAILED",
                "Could not establish ownership of the Windows process tree.",
                self._ownership_failure_details(error, process),
            ) from error

        assert process.stdout is not None and process.stderr is not None
        stdout = _BoundedPipe(
            process.stdout, self.output_limit, keep_tail=False, on_data=progress_callback
        )
        stderr = _BoundedPipe(process.stderr, self.stderr_limit, keep_tail=True)
        stdout.start()
        stderr.start()
        deadline = __import__("time").monotonic() + timeout_seconds
        next_heartbeat = __import__("time").monotonic() + self.heartbeat_interval_seconds
        timed_out = False
        cancelled = False
        try:
            while True:
                if stdout.callback_error is not None:
                    raise stdout.callback_error
                if process.poll() is not None:
                    break
                if cancel_event is not None and cancel_event.is_set():
                    cancelled = True
                    self._terminate_owned_tree(process, windows_job)
                    break
                now = __import__("time").monotonic()
                if heartbeat is not None and now >= next_heartbeat:
                    heartbeat()
                    next_heartbeat = now + self.heartbeat_interval_seconds
                remaining = deadline - now
                if remaining <= 0:
                    timed_out = True
                    self._terminate_owned_tree(process, windows_job)
                    break
                try:
                    process.wait(timeout=min(remaining, 0.05))
                except subprocess.TimeoutExpired:
                    continue
            try:
                if stdout.callback_error is not None:
                    raise stdout.callback_error
                returncode = process.wait(timeout=max(self.grace_seconds, 0.05))
            except subprocess.TimeoutExpired:
                self._terminate_owned_tree(process, windows_job, force=True)
                if os.name == "nt":
                    windows_job = None
                try:
                    returncode = process.wait(timeout=max(self.grace_seconds, 0.05))
                except subprocess.TimeoutExpired as error:
                    raise MediaInfrastructureError(
                        "PROCESS_REAP_FAILED", "Owned media process could not be reaped."
                    ) from error
            else:
                # The parent may exit while a descendant still owns inherited pipes.
                self._terminate_owned_tree(process, windows_job, force=True)
                if os.name == "nt":
                    windows_job = None
                if stdout.callback_error is not None:
                    raise stdout.callback_error
        except BaseException:
            self._terminate_owned_tree(process, windows_job, force=True)
            if os.name == "nt":
                windows_job = None
            try:
                process.wait(timeout=max(self.grace_seconds, 0.05))
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.wait(timeout=max(self.grace_seconds, 0.05))
                except subprocess.TimeoutExpired as error:
                    stdout.close()
                    stderr.close()
                    raise MediaInfrastructureError(
                        "PROCESS_REAP_FAILED", "Owned media process could not be reaped after callback failure."
                    ) from error
            stdout.close()
            stderr.close()
            raise
        finally:
            if windows_job is not None:
                self._close_windows_job(windows_job)
        try:
            stdout_text = stdout.result(max(self.grace_seconds, 0.05))
            stderr_text = stderr.result(max(self.grace_seconds, 0.05))
        except TimeoutError as error:
            self._terminate_owned_tree(process, windows_job, force=True)
            stdout.close()
            stderr.close()
            raise MediaInfrastructureError(
                "PROCESS_REAP_FAILED", "Owned media process descendants retained output pipes."
            ) from error
        return ProcessExecution(
            returncode,
            stdout_text,
            stderr_text,
            timed_out,
            cancelled,
            self._sanitize_argv(argv),
        )

    @staticmethod
    def _sanitize_argv(argv: list[str]) -> tuple[str, ...]:
        sanitized: list[str] = []
        for index, argument in enumerate(argv):
            if index == 0 and Path(argument).is_absolute():
                sanitized.append(f"<tool:{Path(argument).name}>")
                continue
            if Path(argument).is_absolute() or argument.startswith("\\\\"):
                sanitized.append("<path>")
                continue
            redacted = re.sub(r"(?i)[A-Z]:[\\/][^\s,;]+|\\\\[^\s,;]+", "<path>", argument)
            redacted = re.sub(r"(?<![\w.])/(?:[^\s,;]+/)*[^\s,;]*", "<path>", redacted)
            sanitized.append(redacted)
        return tuple(sanitized)

    @staticmethod
    def sanitize_diagnostic(text: str) -> str:
        text = re.sub(r"(?i)[A-Z]:[\\/][^\r\n\"']+", "<path>", text)
        text = re.sub(r"\\\\[^\r\n\"']+", "<path>", text)
        return re.sub(r"(?<![\w.])/(?:[^\s\"']+/)*[^\s\"']*", "<path>", text)

    def _terminate_owned_tree(
        self,
        process: subprocess.Popen[Any],
        windows_job: Any = None,
        force: bool = False,
    ) -> None:
        if process.poll() is not None and not (force and os.name != "nt"):
            if force and os.name == "nt" and windows_job is not None:
                self._close_windows_job(windows_job)
            return
        try:
            if os.name == "nt":
                if not force:
                    process.send_signal(signal.CTRL_BREAK_EVENT)
                    return
                if windows_job is not None:
                    self._close_windows_job(windows_job)
                    return
                self._taskkill_tree(process.pid)
            else:
                os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
            except OSError:
                pass

    @staticmethod
    def _create_windows_job(process: subprocess.Popen[Any]) -> Any:
        import win32api
        import win32job

        try:
            job = win32job.CreateJobObject(None, "")
        except Exception as error:
            raise SubprocessRunner._windows_ownership_failure(
                "create_job", error, process
            ) from error
        try:
            try:
                limits = win32job.QueryInformationJobObject(
                    job, win32job.JobObjectExtendedLimitInformation
                )
            except Exception as error:
                raise SubprocessRunner._windows_ownership_failure(
                    "query_job_limits", error, process
                ) from error
            basic = limits["BasicLimitInformation"]
            basic["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            try:
                win32job.SetInformationJobObject(
                    job, win32job.JobObjectExtendedLimitInformation, limits
                )
            except Exception as error:
                raise SubprocessRunner._windows_ownership_failure(
                    "configure_job_limits", error, process
                ) from error
            try:
                # Popen owns this process handle until the process is reaped;
                # using it avoids a second permission-sensitive OpenProcess.
                win32job.AssignProcessToJobObject(job, process._handle)
            except Exception as error:
                raise SubprocessRunner._windows_ownership_failure(
                    "assign_process_to_job", error, process
                ) from error
            return job
        except Exception:
            win32api.CloseHandle(job)
            raise

    @staticmethod
    def _resume_windows_process(process: subprocess.Popen[Any]) -> None:
        import ctypes
        from ctypes import wintypes

        import win32api
        import win32con
        import win32process

        class THREADENTRY32(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ThreadID", wintypes.DWORD),
                ("th32OwnerProcessID", wintypes.DWORD),
                ("tpBasePri", wintypes.LONG),
                ("tpDeltaPri", wintypes.LONG),
                ("dwFlags", wintypes.DWORD),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(THREADENTRY32)]
        kernel32.Thread32First.restype = wintypes.BOOL
        kernel32.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(THREADENTRY32)]
        kernel32.Thread32Next.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        snapshot = kernel32.CreateToolhelp32Snapshot(0x00000004, 0)  # TH32CS_SNAPTHREAD
        if snapshot == wintypes.HANDLE(-1).value:
            error = ctypes.WinError(ctypes.get_last_error())
            raise SubprocessRunner._windows_ownership_failure(
                "snapshot_threads", error, process
            ) from error
        thread_id: int | None = None
        try:
            entry = THREADENTRY32()
            entry.dwSize = ctypes.sizeof(entry)
            more = bool(kernel32.Thread32First(snapshot, ctypes.byref(entry)))
            while more:
                if entry.th32OwnerProcessID == process.pid:
                    thread_id = int(entry.th32ThreadID)
                    break
                more = bool(kernel32.Thread32Next(snapshot, ctypes.byref(entry)))
        finally:
            kernel32.CloseHandle(snapshot)
        if thread_id is None:
            error = OSError("the suspended process primary thread was not found")
            raise SubprocessRunner._windows_ownership_failure(
                "find_primary_thread", error, process
            ) from error
        try:
            thread = win32api.OpenThread(
                win32con.THREAD_SUSPEND_RESUME, False, thread_id
            )
        except Exception as error:
            raise SubprocessRunner._windows_ownership_failure(
                "open_primary_thread", error, process
            ) from error
        try:
            try:
                previous_count = win32process.ResumeThread(thread)
            except Exception as error:
                raise SubprocessRunner._windows_ownership_failure(
                    "resume_primary_thread", error, process
                ) from error
            if previous_count != 1:
                error = RuntimeError(
                    f"unexpected primary-thread suspend count: {previous_count}"
                )
                raise SubprocessRunner._windows_ownership_failure(
                    "resume_primary_thread", error, process
                ) from error
        finally:
            win32api.CloseHandle(thread)

    @staticmethod
    def _windows_ownership_failure(
        stage: str, error: BaseException, process: subprocess.Popen[Any]
    ) -> _WindowsOwnershipFailure:
        import win32job

        try:
            process_exited: bool | None = process.poll() is not None
        except Exception:
            process_exited = None
        try:
            already_in_job: bool | None = bool(
                win32job.IsProcessInJob(process._handle, None)
            )
        except Exception:
            already_in_job = None
        return _WindowsOwnershipFailure(
            stage,
            error,
            process_exited=process_exited,
            already_in_job=already_in_job,
        )

    @staticmethod
    def _ownership_failure_details(
        error: BaseException, process: subprocess.Popen[Any]
    ) -> dict[str, Any]:
        if isinstance(error, _WindowsOwnershipFailure):
            return {
                "stage": error.stage,
                "windows_error": error.windows_error,
                "process_exited": error.process_exited,
                "already_in_job": error.already_in_job,
            }
        return {
            "stage": "unexpected_ownership_error",
            "windows_error": _windows_error_code(error),
            "process_exited": process.poll() is not None,
            "already_in_job": None,
        }

    @staticmethod
    def _close_windows_job(job: Any) -> None:
        import win32api

        win32api.CloseHandle(job)

    @staticmethod
    def _taskkill_tree(process_id: int) -> None:
        taskkill = str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe")
        subprocess.run(
            [taskkill, "/PID", str(process_id), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            timeout=5.0,
            check=False,
        )


def _windows_error_code(error: BaseException) -> int | None:
    value = getattr(error, "winerror", None)
    if isinstance(value, int):
        return value
    args = getattr(error, "args", ())
    return args[0] if args and isinstance(args[0], int) else None
