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
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

KERNEL_SCRIPT = Path(__file__).resolve().parent / "study_kernel.py"
MAX_KERNELS = 8
EXECUTE_TIMEOUT_SECONDS = 120.0


class KernelUnavailable(RuntimeError):
    """The Python runtime cannot currently execute cells."""


class KernelError(RuntimeError):
    """A cell-level failure reported to the user."""


def _utf8_environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    return environment


@dataclass
class _Pending:
    event: threading.Event = field(default_factory=threading.Event)
    slot: dict[str, Any] = field(default_factory=dict)


class KernelProcess:
    """One ``study_kernel.py`` bridge process bound to one notebook."""

    def __init__(self, command: list[str], on_exit: Any) -> None:
        self._lock = threading.RLock()
        self._on_exit = on_exit
        self._pending: dict[str, _Pending] = {}
        self._stderr_tail = ""
        self.last_used = time.monotonic()
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self._process = subprocess.Popen(
                [*command, "-X", "utf8", "-u", str(KERNEL_SCRIPT)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                env=_utf8_environment(),
                creationflags=creationflags,
            )
        except OSError as exc:
            raise KernelUnavailable(f"Could not start the CPython kernel: {exc}") from exc
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

    def _read_stdout(self) -> None:
        assert self._process.stdout is not None
        for line in self._process.stdout:
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
        # The process ended: resolve anything outstanding as failed.
        self.fail("The CPython kernel exited unexpectedly")
        try:
            self._on_exit(self)
        except Exception:
            pass

    def _drain_stderr(self) -> None:
        assert self._process.stderr is not None
        try:
            tail = self._process.stderr.read() or ""
        except (OSError, ValueError):
            tail = ""
        with self._lock:
            self._stderr_tail = tail[-8_000:]

    def execute(self, source: str) -> dict[str, Any]:
        if not self.alive:
            raise KernelUnavailable("The CPython kernel is not running")
        request_id = uuid.uuid4().hex
        pending = _Pending()
        with self._lock:
            if self._pending:
                raise KernelError("This notebook's CPython kernel is already running a cell")
            self._pending[request_id] = pending
        assert self._process.stdin is not None
        try:
            self._process.stdin.write(json.dumps({"id": request_id, "source": source}) + "\n")
            self._process.stdin.flush()
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
        if self.alive:
            try:
                self._process.kill()
            except OSError:
                pass
        try:
            self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


class StudyPythonRuntime:
    """Owns at most MAX_KERNELS bridge processes, one per notebook."""

    def __init__(self, python_command: list[str] | None = None) -> None:
        self.command = python_command or [sys.executable]
        self._kernels: dict[str, KernelProcess] = {}
        self._lock = threading.RLock()

    def status(self) -> dict[str, Any]:
        with self._lock:
            alive = sum(1 for kernel in self._kernels.values() if kernel.alive)
        return {
            "available": True,
            "python": self.command[0],
            "runningKernels": alive,
            "maxKernels": MAX_KERNELS,
        }

    def run(self, notebook_id: str, source: str) -> dict[str, Any]:
        with self._lock:
            kernel = self._kernels.get(notebook_id)
            if kernel is not None and not kernel.alive:
                self._kernels.pop(notebook_id, None)
                kernel = None
            if kernel is None:
                if len(self._kernels) >= MAX_KERNELS:
                    oldest_id, oldest = min(
                        self._kernels.items(),
                        key=lambda item: item[1].last_used,
                    )
                    oldest.stop("An idle kernel was closed to make room for another notebook")
                    self._kernels.pop(oldest_id, None)
                kernel = KernelProcess(self.command, on_exit=self._handle_exit)
                self._kernels[notebook_id] = kernel
        try:
            return kernel.execute(source)
        except (KernelError, KernelUnavailable):
            raise
        except Exception as exc:  # Surface unexpected failures as cell errors.
            raise KernelError(f"The CPython kernel failed: {exc}") from exc

    def restart(self, notebook_id: str) -> dict[str, Any]:
        with self._lock:
            kernel = self._kernels.pop(notebook_id, None)
        if kernel is not None:
            kernel.stop("The CPython kernel was restarted; previous variables are gone")
        return {"ok": True}

    def stop_all(self) -> None:
        with self._lock:
            kernels = list(self._kernels.values())
            self._kernels.clear()
        for kernel in kernels:
            kernel.stop("Lattice is shutting down")

    def _handle_exit(self, kernel: KernelProcess) -> None:
        with self._lock:
            for key, value in list(self._kernels.items()):
                if value is kernel:
                    self._kernels.pop(key, None)
