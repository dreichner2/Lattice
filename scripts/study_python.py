"""Supervision for Study Lab's persistent CPython kernels.

A faithful re-expression of Lunaris's ``python-runtime.mjs`` in Python: the
library service spawns one ``study_kernel.py`` bridge process per notebook,
speaks newline-delimited JSON over stdio, and enforces the same guarantees —
one execution at a time per kernel, a bounded kernel count with idle
eviction, and restart semantics.

Execution is trusted local code with full user permissions. This is not a
sandbox; that posture stays documented in SECURITY.md.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

KERNEL_SCRIPT = Path(__file__).resolve().parent / "study_kernel.py"
MAX_KERNELS = 8
EXECUTE_TIMEOUT_SECONDS = 120.0
STDERR_TAIL_CHARACTERS = 8_000
MAX_CONTROL_REQUEST_CHARACTERS = 1_000_000
MAX_CONTROL_REPLY_CHARACTERS = 52_000_000


class KernelUnavailable(RuntimeError):
    """The Python runtime cannot currently execute cells."""


class KernelError(RuntimeError):
    """A cell-level failure reported to the user."""


class _WindowsJob:
    """Own a Windows process tree that dies when its kernel is stopped.

    ``CREATE_NEW_PROCESS_GROUP`` does not recursively terminate descendants.
    A kill-on-close Job Object does, including grandchildren that inherited no
    Lattice handles. The implementation is kept behind the platform check so
    source builds on macOS/Linux do not import Windows-only ctypes symbols.
    """

    def __init__(self, process: subprocess.Popen[str]) -> None:
        if os.name != "nt":
            raise OSError("Windows Job Objects are only available on Windows")

        import ctypes
        from ctypes import wintypes

        class _BasicLimitInformation(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class _IoCounters(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class _ExtendedLimitInformation(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", _BasicLimitInformation),
                ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.TerminateJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self._kernel32 = kernel32
        self._handle = handle
        self._lock = threading.Lock()
        try:
            information = _ExtendedLimitInformation()
            information.BasicLimitInformation.LimitFlags = 0x00002000  # KILL_ON_JOB_CLOSE
            if not kernel32.SetInformationJobObject(
                handle,
                9,  # JobObjectExtendedLimitInformation
                ctypes.byref(information),
                ctypes.sizeof(information),
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            process_handle = wintypes.HANDLE(int(process._handle))  # type: ignore[attr-defined]
            if not kernel32.AssignProcessToJobObject(handle, process_handle):
                raise ctypes.WinError(ctypes.get_last_error())
        except BaseException:
            kernel32.CloseHandle(handle)
            self._handle = None
            raise

    def terminate(self) -> None:
        with self._lock:
            handle = self._handle
            if handle is not None:
                self._kernel32.TerminateJobObject(handle, 1)

    def close(self) -> None:
        with self._lock:
            handle = self._handle
            self._handle = None
        if handle is not None:
            self._kernel32.CloseHandle(handle)


def _utf8_environment() -> dict[str, str]:
    environment = dict(os.environ)
    # The launch capability belongs to the owning Lattice webview, not to code
    # entered in a notebook. Python cells are trusted local execution, but they
    # still do not need this service secret in their inherited environment.
    environment.pop("LATTICE_PRIVATE_TOKEN", None)
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    return environment


def _kernel_launch_command(command: list[str], *, frozen: bool) -> list[str]:
    """Build the bridge command for source and PyInstaller runtimes."""
    if frozen:
        # The packaged Windows service owns its embedded interpreter. Re-enter
        # the executable through server_bootstrap's narrow bridge-only mode.
        return [*command, "--study-kernel"]
    return [*command, "-X", "utf8", "-u", str(KERNEL_SCRIPT)]


@dataclass
class _Pending:
    event: threading.Event = field(default_factory=threading.Event)
    slot: dict[str, Any] = field(default_factory=dict)


class KernelProcess:
    """One ``study_kernel.py`` bridge process bound to one notebook."""

    def __init__(
        self,
        command: list[str],
        on_exit: Any,
        *,
        working_directory: Path,
    ) -> None:
        self._lock = threading.RLock()
        self._on_exit = on_exit
        self._pending: dict[str, _Pending] = {}
        self._reserved = False
        self._stderr_tail = ""
        self._stop_lock = threading.Lock()
        self._stopped = False
        self._stop_complete = threading.Event()
        self._job: _WindowsJob | None = None
        self.last_used = time.monotonic()
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                env=_utf8_environment(),
                cwd=os.fspath(working_directory),
                creationflags=creationflags,
                start_new_session=os.name != "nt",
            )
        except OSError as exc:
            raise KernelUnavailable(f"Could not start the CPython kernel: {exc}") from exc
        if os.name == "nt":
            try:
                self._job = _WindowsJob(self._process)
            except OSError as exc:
                self._process.kill()
                self._process.wait(timeout=5)
                for stream in (self._process.stdin, self._process.stdout, self._process.stderr):
                    if stream is not None:
                        stream.close()
                raise KernelUnavailable(
                    f"Could not contain the CPython kernel process tree: {exc}"
                ) from exc
        self._stdout_thread = threading.Thread(
            target=self._read_stdout,
            name="study-kernel-stdout",
            daemon=True,
        )
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr,
            name="study-kernel-stderr",
            daemon=True,
        )
        self._stdout_thread.start()
        self._stderr_thread.start()

    @property
    def alive(self) -> bool:
        return self._process.poll() is None

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._reserved or bool(self._pending)

    def reserve(self) -> None:
        with self._lock:
            if self._reserved or self._pending:
                raise KernelError("This notebook's CPython kernel is already running a cell")
            self._reserved = True

    def release(self) -> None:
        with self._lock:
            self._reserved = False

    def _read_stdout(self) -> None:
        assert self._process.stdout is not None
        try:
            while True:
                line = self._process.stdout.readline(MAX_CONTROL_REPLY_CHARACTERS + 1)
                if not line:
                    break
                if len(line) > MAX_CONTROL_REPLY_CHARACTERS or not line.endswith("\n"):
                    self.fail("The CPython kernel returned an oversized control message")
                    self._terminate_process_tree()
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(message, dict):
                    continue
                request_id = str(message.get("id") or "")
                with self._lock:
                    pending = self._pending.pop(request_id, None)
                if pending is None:
                    continue
                pending.slot.update(message)
                pending.event.set()
        except (OSError, ValueError):
            pass
        finally:
            # A bridge exit also owns and cleans up any notebook descendants.
            self.stop("The CPython kernel exited unexpectedly")
            try:
                self._on_exit(self)
            except Exception:
                pass

    def _drain_stderr(self) -> None:
        assert self._process.stderr is not None
        try:
            while True:
                chunk = self._process.stderr.read(4_096)
                if not chunk:
                    break
                with self._lock:
                    self._stderr_tail = (
                        self._stderr_tail + chunk
                    )[-STDERR_TAIL_CHARACTERS:]
        except (OSError, ValueError):
            pass

    def execute(self, source: str) -> dict[str, Any]:
        if not self.alive:
            raise KernelUnavailable("The CPython kernel is not running")
        request_id = uuid.uuid4().hex
        pending = _Pending()
        with self._lock:
            self._pending[request_id] = pending
        assert self._process.stdin is not None
        try:
            request = json.dumps({"id": request_id, "source": source})
            if len(request) > MAX_CONTROL_REQUEST_CHARACTERS:
                raise KernelError("The cell is too large for the kernel control channel")
            self._process.stdin.write(request + "\n")
            self._process.stdin.flush()
        except KernelError:
            with self._lock:
                self._pending.pop(request_id, None)
            raise
        except (OSError, ValueError) as exc:
            with self._lock:
                self._pending.pop(request_id, None)
            raise KernelUnavailable(f"Could not send the cell to the kernel: {exc}") from exc
        self.last_used = time.monotonic()
        if not pending.event.wait(EXECUTE_TIMEOUT_SECONDS):
            self.stop("The cell exceeded its execution time limit")
            raise KernelError(
                "The cell timed out. The kernel was stopped so one long run cannot hang the notebook."
            )
        ok = bool(pending.slot.get("ok"))
        outputs = pending.slot.get("outputs")
        return {
            "ok": ok,
            "outputs": outputs if isinstance(outputs, list) else [],
        }

    def _error_reply(self, message: str) -> dict[str, Any]:
        with self._lock:
            tail = self._stderr_tail[-2_000:]
        return {
            "ok": False,
            "outputs": [{
                "type": "error",
                "name": "KernelDied",
                "message": message,
                "traceback": tail,
            }],
        }

    def fail(self, message: str) -> None:
        """Resolve every outstanding request with an error reply."""
        with self._lock:
            outstanding = list(self._pending.values())
            self._pending.clear()
        reply = self._error_reply(message)
        for pending in outstanding:
            pending.slot.update(reply)
            pending.event.set()

    def stop(self, reason: str = "The CPython kernel was stopped") -> None:
        self.fail(reason)
        with self._stop_lock:
            owner = not self._stopped
            if owner:
                self._stopped = True
        if not owner:
            # A reader thread can discover EOF while the elected owner is
            # joining that same thread. External lifecycle callers must wait;
            # the reader must return so the owner can complete the join.
            if threading.current_thread() in (self._stdout_thread, self._stderr_thread):
                return
            self._stop_complete.wait()
            return
        try:
            self._terminate_process_tree()
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    self._terminate_process_tree()
                    self._process.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            # Closing the parent-side pipe endpoints unblocks reader threads
            # even if deliberately detached trusted code escaped the managed
            # process tree.
            for stream in (self._process.stdin, self._process.stdout, self._process.stderr):
                if stream is not None and not stream.closed:
                    try:
                        stream.close()
                    except (OSError, ValueError):
                        pass
            for thread in (self._stdout_thread, self._stderr_thread):
                if thread is not threading.current_thread():
                    thread.join(timeout=1)
        finally:
            self._stop_complete.set()

    def _terminate_process_tree(self) -> None:
        """Best-effort hard stop for the bridge and every managed descendant."""
        job = self._job
        if job is not None:
            job.terminate()
            job.close()
            self._job = None
        elif os.name != "nt":
            try:
                # start_new_session makes the bridge PID its process-group ID.
                os.killpg(self._process.pid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                pass
        if self.alive:
            try:
                self._process.kill()
            except OSError:
                pass


class StudyPythonRuntime:
    """Owns at most MAX_KERNELS bridge processes, one per notebook."""

    def __init__(
        self,
        python_command: list[str] | None = None,
        *,
        frozen: bool | None = None,
        working_directory: Path | None = None,
    ) -> None:
        self.command = python_command or [sys.executable]
        self.frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
        requested_working_directory = working_directory or Path(tempfile.gettempdir())
        try:
            self.working_directory = requested_working_directory.expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise KernelUnavailable(
                "The private Study Lab working directory is unavailable"
            ) from exc
        if not self.working_directory.is_dir():
            raise KernelUnavailable(
                "The private Study Lab working directory is unavailable"
            )
        self._kernels: dict[str, KernelProcess] = {}
        self._lock = threading.RLock()
        self._closed = False
        self._generations: dict[str, int] = {}
        self._retired: set[str] = set()
        self._retiring: set[str] = set()
        self._stopping_kernels: set[KernelProcess] = set()

    def status(self) -> dict[str, Any]:
        with self._lock:
            alive = sum(1 for kernel in self._kernels.values() if kernel.alive)
            available = not self._closed
        return {
            "available": available,
            "python": self.command[0],
            "runningKernels": alive,
            "maxKernels": MAX_KERNELS,
        }

    def _require_admission(self, notebook_id: str) -> None:
        if self._closed:
            raise KernelUnavailable("The Study Lab Python runtime is shutting down")
        if notebook_id in self._retired:
            raise KernelUnavailable("This notebook was deleted")
        if notebook_id in self._retiring:
            raise KernelUnavailable("This notebook's CPython kernel is restarting")

    def _acquire(
        self,
        notebook_id: str,
        validate: Callable[[], Any] | None,
    ) -> tuple[KernelProcess, int]:
        while True:
            eviction: KernelProcess | None = None
            with self._lock:
                self._require_admission(notebook_id)
                if validate is not None:
                    # Storage validation and kernel reservation share this one
                    # short admission boundary with delete/restart.
                    validate()
                kernel = self._kernels.get(notebook_id)
                if kernel is not None and not kernel.alive:
                    self._kernels.pop(notebook_id, None)
                    self._generations[notebook_id] = (
                        self._generations.get(notebook_id, 0) + 1
                    )
                    kernel = None
                if kernel is None:
                    managed_count = len(self._kernels) + len(self._stopping_kernels)
                    if managed_count >= MAX_KERNELS:
                        idle = [
                            item for item in self._kernels.items()
                            if not item[1].busy
                        ]
                        if not idle or self._stopping_kernels:
                            raise KernelUnavailable(
                                "All Study Lab kernels are busy; wait for a cell to finish"
                            )
                        oldest_id, eviction = min(
                            idle,
                            key=lambda item: item[1].last_used,
                        )
                        self._kernels.pop(oldest_id, None)
                        self._generations[oldest_id] = (
                            self._generations.get(oldest_id, 0) + 1
                        )
                        self._stopping_kernels.add(eviction)
                    else:
                        kernel = KernelProcess(
                            _kernel_launch_command(self.command, frozen=self.frozen),
                            on_exit=self._handle_exit,
                            working_directory=self.working_directory,
                        )
                        self._kernels[notebook_id] = kernel
                if eviction is None:
                    assert kernel is not None
                    kernel.reserve()
                    return kernel, self._generations.get(notebook_id, 0)
            try:
                eviction.stop(
                    "An idle kernel was closed to make room for another notebook"
                )
            finally:
                with self._lock:
                    self._stopping_kernels.discard(eviction)

    def run(
        self,
        notebook_id: str,
        source: str,
        *,
        validate: Callable[[], Any] | None = None,
    ) -> dict[str, Any]:
        kernel, generation = self._acquire(notebook_id, validate)
        try:
            result = kernel.execute(source)
        except (KernelError, KernelUnavailable):
            raise
        except Exception as exc:  # Surface unexpected failures as cell errors.
            raise KernelError(f"The CPython kernel failed: {exc}") from exc
        finally:
            kernel.release()
        with self._lock:
            if (
                self._closed
                or notebook_id in self._retired
                or self._generations.get(notebook_id, 0) != generation
                or self._kernels.get(notebook_id) is not kernel
            ):
                raise KernelUnavailable(
                    "The kernel changed while this cell was running; its stale result was discarded"
                )
        return result

    def _retire_notebook(
        self,
        notebook_id: str,
        *,
        transition: Callable[[], Any] | None,
        permanent: bool,
        reason: str,
    ) -> Any:
        with self._lock:
            self._require_admission(notebook_id)
            result = transition() if transition is not None else None
            self._retiring.add(notebook_id)
            self._generations[notebook_id] = self._generations.get(notebook_id, 0) + 1
            if permanent:
                self._retired.add(notebook_id)
            kernel = self._kernels.pop(notebook_id, None)
            if kernel is not None:
                self._stopping_kernels.add(kernel)
        try:
            if kernel is not None:
                kernel.stop(reason)
        finally:
            with self._lock:
                self._retiring.discard(notebook_id)
                if kernel is not None:
                    self._stopping_kernels.discard(kernel)
        return result

    def restart(
        self,
        notebook_id: str,
        *,
        validate: Callable[[], Any] | None = None,
    ) -> dict[str, Any]:
        self._retire_notebook(
            notebook_id,
            transition=validate,
            permanent=False,
            reason="The CPython kernel was restarted; previous variables are gone",
        )
        return {"ok": True}

    def delete_notebook(
        self,
        notebook_id: str,
        delete: Callable[[], Any],
    ) -> Any:
        return self._retire_notebook(
            notebook_id,
            transition=delete,
            permanent=True,
            reason="The notebook was deleted",
        )

    def stop_all(self) -> None:
        with self._lock:
            self._closed = True
            active_kernels = list(self._kernels.values())
            for notebook_id in self._kernels:
                self._generations[notebook_id] = (
                    self._generations.get(notebook_id, 0) + 1
                )
            self._kernels.clear()
            self._stopping_kernels.update(active_kernels)
            kernels = list(self._stopping_kernels)
        try:
            for kernel in kernels:
                kernel.stop("Lattice is shutting down")
        finally:
            with self._lock:
                for kernel in kernels:
                    self._stopping_kernels.discard(kernel)

    def _handle_exit(self, kernel: KernelProcess) -> None:
        with self._lock:
            for key, value in list(self._kernels.items()):
                if value is kernel:
                    self._kernels.pop(key, None)
                    self._generations[key] = self._generations.get(key, 0) + 1
