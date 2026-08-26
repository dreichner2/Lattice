"""Persistent CPython execution bridge for the Lattice Study Lab.

The local library service owns this process and sends framed newline-JSON over
private duplicated descriptors. Notebook-native standard I/O is permanently
detached from those descriptors; bounded Python stream writes become structured
outputs. This is a faithful port of Lunaris's ``lunaris_kernel.py`` minus its
WebAgg interactive-plot layer — Study Lab serves PNG captures only.

Execution is trusted: cells run with full user permissions in a persistent
namespace. This is not a sandbox.
"""

from __future__ import annotations

import ast
import base64
import builtins
import collections
import contextlib
import io
import itertools
import json
import os
import sys
import threading
import warnings
from typing import Any

MAX_OUTPUT_CHARACTERS = 100_000
MAX_PLOTS = 8
MAX_PLOT_BYTES = 4_000_000
MAX_TRACEBACK_FRAMES = 50
MAX_CONTAINER_ITEMS = 100
MAX_CONTROL_REQUEST_CHARACTERS = 1_000_000
MAX_CONTROL_REPLY_CHARACTERS = 52_000_000

# Notebook runs must never open a platform GUI or block on plt.show(). Users can
# still choose another backend explicitly inside trusted code when they need it.
os.environ["MPLBACKEND"] = os.environ.get("LATTICE_MATPLOTLIB_BACKEND", "Agg")
warnings.filterwarnings("ignore", message=r"FigureCanvasAgg is non-interactive.*", category=UserWarning)

# One request executes at a time; matplotlib figure capture is not thread-safe
# and interleaved execs would corrupt the shared namespace anyway.
RUN_LOCK = threading.Lock()


def _blocked_input(prompt: str = "") -> str:
    raise RuntimeError("input() needs a terminal prompt and is not available inside a notebook run")


_REAL_INPUT = builtins.input
builtins.input = _blocked_input

NAMESPACE: dict[str, Any] = {
    "__name__": "__main__",
    "__builtins__": builtins,
}

# Call type's concrete descriptors directly when labeling arbitrary values.
# Ordinary attribute lookup on a class can execute a custom metaclass data
# descriptor, including one named ``__module__``. These descriptors read the
# underlying CPython type fields without that polymorphic dispatch.
_TYPE_NAME_DESCRIPTOR = type.__dict__["__name__"]
_TYPE_QUALNAME_DESCRIPTOR = type.__dict__["__qualname__"]
_TYPE_MODULE_DESCRIPTOR = type.__dict__["__module__"]


class _BoundedTextBuffer(io.TextIOBase):
    """A text sink that discards overflow instead of retaining it in memory."""

    def __init__(self, limit: int = MAX_OUTPUT_CHARACTERS) -> None:
        super().__init__()
        self._limit = limit
        self._parts: list[str] = []
        self._length = 0
        self.truncated = False

    def writable(self) -> bool:
        return True

    def write(self, value: str) -> int:
        if not isinstance(value, str):
            raise TypeError("notebook text streams accept str values")
        # ``TextIOBase`` accepts ``str`` subclasses, but their Python-level
        # ``__len__`` and ``__getitem__`` methods are arbitrary notebook code.
        # Invoke the exact built-in operations so an overridden slice cannot
        # expand a tiny write into an unbounded retained string.
        incoming = str.__len__(value)
        remaining = self._limit - self._length
        if remaining > 0:
            kept = str.__getitem__(value, slice(0, remaining))
            self._parts.append(kept)
            self._length += str.__len__(kept)
        if incoming > max(remaining, 0):
            self.truncated = True
        return incoming

    def getvalue(self) -> str:
        return "".join(self._parts)


class _PlotTooLarge(RuntimeError):
    pass


class _BoundedBytesIO(io.BytesIO):
    """Abort plot encoding before an in-memory PNG can exceed its limit."""

    def __init__(self, limit: int) -> None:
        super().__init__()
        self._limit = limit

    def write(self, value: Any) -> int:
        size = len(value)
        if self.tell() + size > self._limit:
            raise _PlotTooLarge
        return super().write(value)


def _bounded_literal(value: str | bytes, limit: int) -> tuple[str, bool]:
    # Slicing first bounds the temporary produced by repr, including escape
    # expansion for control characters and non-ASCII text.
    preview = value[:limit]
    rendered = repr(preview)
    truncated = len(value) > len(preview) or len(rendered) > limit
    if len(rendered) > limit:
        rendered = rendered[:limit]
    return rendered, truncated


def _raw_type_text(
    value_type: type[Any],
    descriptor: Any,
    *,
    limit: int,
    fallback: str,
) -> str:
    try:
        candidate = descriptor.__get__(value_type, type(value_type))
    except (AttributeError, TypeError):
        return fallback
    if not isinstance(candidate, str):
        return fallback
    return str.__getitem__(candidate, slice(0, limit))


def _type_name(value: Any, *, limit: int = 200, fallback: str = "value") -> str:
    value_type = type(value)
    return _raw_type_text(
        value_type,
        _TYPE_NAME_DESCRIPTOR,
        limit=limit,
        fallback=fallback,
    )


def _type_label(value: Any) -> str:
    value_type = type(value)
    module = _raw_type_text(
        value_type,
        _TYPE_MODULE_DESCRIPTOR,
        limit=200,
        fallback="",
    )
    name = _raw_type_text(
        value_type,
        _TYPE_QUALNAME_DESCRIPTOR,
        limit=200,
        fallback=_type_name(value),
    )
    return f"{module}.{name}" if module and module != "builtins" else name


def _safe_repr(
    value: Any,
    limit: int = MAX_OUTPUT_CHARACTERS,
    *,
    depth: int = 0,
    seen: set[int] | None = None,
) -> tuple[str, bool]:
    """Represent common values without invoking unbounded user ``__repr__``."""
    if limit <= 0:
        return "", True
    value_type = type(value)
    if value_type in {str, bytes}:
        return _bounded_literal(value, limit)
    if value is None or value_type in {bool, float, complex}:
        rendered = repr(value)
        return rendered[:limit], len(rendered) > limit
    if value_type is int:
        # A disabled sys.int_max_str_digits must not permit a giant decimal
        # conversion. Normal-sized integers preserve their ordinary repr.
        if value.bit_length() > limit * 3:
            rendered = f"<int with {value.bit_length():,} bits>"
            return rendered[:limit], True
        rendered = repr(value)
        return rendered[:limit], len(rendered) > limit
    if value_type is range:
        range_values = [value.start, value.stop]
        if value.step != 1:
            range_values.append(value.step)
        parts: list[str] = []
        truncated = False
        for item in range_values:
            remaining = max(1, limit - len("range(, , )") - sum(map(len, parts)))
            rendered, cut = _safe_repr(
                item,
                remaining,
                depth=depth + 1,
                seen=seen,
            )
            parts.append(rendered)
            truncated = truncated or cut
        rendered = f"range({', '.join(parts)})"
        return rendered[:limit], truncated or len(rendered) > limit
    if value_type is slice:
        parts: list[str] = []
        truncated = False
        for item in (value.start, value.stop, value.step):
            remaining = max(1, limit - len("slice(, , )") - sum(map(len, parts)))
            rendered, cut = _safe_repr(
                item,
                remaining,
                depth=depth + 1,
                seen=seen,
            )
            parts.append(rendered)
            truncated = truncated or cut
        rendered = f"slice({', '.join(parts)})"
        return rendered[:limit], truncated or len(rendered) > limit

    if seen is None:
        seen = set()
    identity = id(value)
    if identity in seen:
        return "<recursive value>"[:limit], True
    if depth >= 6:
        rendered = f"<{_type_label(value)} value>"
        return rendered[:limit], True

    if value_type in {list, tuple, set, frozenset, dict}:
        seen.add(identity)
        try:
            if value_type is dict:
                opener, closer = "{", "}"
                items = list(itertools.islice(value.items(), MAX_CONTAINER_ITEMS))
            elif value_type is list:
                opener, closer = "[", "]"
                items = value[:MAX_CONTAINER_ITEMS]
            elif value_type is tuple:
                opener, closer = "(", ")"
                items = value[:MAX_CONTAINER_ITEMS]
            elif value_type is set:
                if not value:
                    return "set()"[:limit], False
                opener, closer = "{", "}"
                items = list(itertools.islice(value, MAX_CONTAINER_ITEMS))
            else:
                if not value:
                    return "frozenset()"[:limit], False
                opener, closer = "frozenset({", "})"
                items = list(itertools.islice(value, MAX_CONTAINER_ITEMS))

            rendered = opener
            truncated = len(value) > len(items)
            for index, item in enumerate(items):
                separator = ", " if index else ""
                remaining = limit - len(rendered) - len(separator) - len(closer)
                if remaining <= 0:
                    truncated = True
                    break
                if value_type is dict:
                    key, child = item
                    key_text, key_cut = _safe_repr(
                        key,
                        max(1, remaining // 2),
                        depth=depth + 1,
                        seen=seen,
                    )
                    child_remaining = remaining - len(key_text) - 2
                    child_text, child_cut = _safe_repr(
                        child,
                        max(1, child_remaining),
                        depth=depth + 1,
                        seen=seen,
                    )
                    part = f"{key_text}: {child_text}"
                    truncated = truncated or key_cut or child_cut
                else:
                    part, child_cut = _safe_repr(
                        item,
                        remaining,
                        depth=depth + 1,
                        seen=seen,
                    )
                    truncated = truncated or child_cut
                rendered += separator + part[:remaining]
                if len(part) > remaining:
                    truncated = True
                    break
            if truncated:
                marker = ", ..." if rendered != opener else "..."
                room = limit - len(closer)
                rendered = rendered[: max(0, room - len(marker))] + marker
            if value_type is tuple and len(value) == 1 and not truncated:
                rendered += ","
            rendered += closer
            return rendered[:limit], truncated or len(rendered) > limit
        finally:
            seen.discard(identity)

    # Calling arbitrary __repr__ is itself arbitrary code and may allocate an
    # unbounded string. Preserve a useful type marker instead.
    rendered = f"<{_type_label(value)} instance>"
    return rendered[:limit], len(rendered) > limit


def _safe_exception_message(error: BaseException) -> tuple[str, bool]:
    try:
        args = BaseException.__getattribute__(error, "args")
    except (AttributeError, TypeError):
        args = ()
    if len(args) == 1 and type(args[0]) is str:
        message = args[0]
        return message[:MAX_OUTPUT_CHARACTERS], len(message) > MAX_OUTPUT_CHARACTERS
    if not args:
        return "", False
    return _safe_repr(tuple(args))


def _safe_traceback(
    error: BaseException,
    name: str,
    message: str,
) -> tuple[str, bool]:
    buffer = _BoundedTextBuffer()
    frames: collections.deque[Any] = collections.deque(maxlen=MAX_TRACEBACK_FRAMES)
    frame_count = 0
    current = error.__traceback__
    while current is not None:
        frames.append(current)
        frame_count += 1
        current = current.tb_next
    if frames:
        buffer.write("Traceback (most recent call last):\n")
    for item in frames:
        code = item.tb_frame.f_code
        filename = str(code.co_filename)[:2_000]
        function = str(code.co_name)[:500]
        buffer.write(f'  File "{filename}", line {item.tb_lineno}, in {function}\n')
    if frame_count > MAX_TRACEBACK_FRAMES:
        buffer.truncated = True
    buffer.write(f"{name}: {message}\n")
    return buffer.getvalue(), buffer.truncated


def _stream(
    name: str,
    value: str,
    *,
    truncated: bool = False,
) -> dict[str, Any] | None:
    if not value:
        return None
    text = value[:MAX_OUTPUT_CHARACTERS]
    truncated = truncated or len(value) > MAX_OUTPUT_CHARACTERS
    output: dict[str, Any] = {"type": "stream", "name": name, "text": text}
    if truncated:
        output["truncated"] = True
    return output


def _capture_plots() -> tuple[list[dict[str, Any]], str]:
    if "matplotlib.pyplot" not in sys.modules:
        return [], ""
    try:
        import matplotlib.pyplot as plt

        outputs: list[dict[str, Any]] = []
        notes: list[str] = []
        figure_numbers = list(plt.get_fignums())
        for figure_number in figure_numbers[:MAX_PLOTS]:
            figure = plt.figure(figure_number)
            buffer = _BoundedBytesIO(MAX_PLOT_BYTES)
            try:
                figure.savefig(buffer, format="png", bbox_inches="tight")
                data = buffer.getvalue()
            except _PlotTooLarge:
                notes.append(
                    f"Plot {figure_number} was omitted because its PNG exceeded {MAX_PLOT_BYTES:,} bytes.\n"
                )
                continue
            finally:
                buffer.close()
            outputs.append({
                "type": "image",
                "mime": "image/png",
                "data": base64.b64encode(data).decode("ascii"),
            })
        if len(figure_numbers) > MAX_PLOTS:
            notes.append(f"Only the first {MAX_PLOTS} plots were kept.\n")
        plt.close("all")
        return outputs, "".join(notes)
    except Exception as error:  # Plot capture must not hide a successful calculation.
        message, _truncated = _safe_exception_message(error)
        return [], f"Lattice could not capture a plot: {message}\n"


def _execute(source: str) -> dict[str, Any]:
    stdout = _BoundedTextBuffer()
    stderr = _BoundedTextBuffer()
    outputs: list[dict[str, Any]] = []
    result: Any = None
    ok = True
    error_output: dict[str, Any] | None = None

    try:
        with RUN_LOCK, contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            module = ast.parse(source, filename="<study-cell>", mode="exec")
            if module.body and isinstance(module.body[-1], ast.Expr):
                prefix = ast.Module(body=module.body[:-1], type_ignores=[])
                if prefix.body:
                    exec(compile(prefix, "<study-cell>", "exec"), NAMESPACE, NAMESPACE)
                expression = ast.Expression(module.body[-1].value)
                result = eval(compile(expression, "<study-cell>", "eval"), NAMESPACE, NAMESPACE)
                NAMESPACE["_"] = result
            else:
                exec(compile(module, "<study-cell>", "exec"), NAMESPACE, NAMESPACE)
    except BaseException as error:  # Notebook exceptions become cell outputs; the kernel stays alive.
        ok = False
        name = _type_name(error, limit=500, fallback="Exception")
        message, message_truncated = _safe_exception_message(error)
        limited_trace, trace_truncated = _safe_traceback(error, name, message)
        error_output = {
            "type": "error",
            "name": name,
            "message": message,
            "traceback": limited_trace,
        }
        if message_truncated or trace_truncated:
            error_output["truncated"] = True

    stdout_output = _stream("stdout", stdout.getvalue(), truncated=stdout.truncated)
    stderr_output = _stream("stderr", stderr.getvalue(), truncated=stderr.truncated)
    if stdout_output:
        outputs.append(stdout_output)
    if stderr_output:
        outputs.append(stderr_output)
    if ok and result is not None:
        rendered, truncated = _safe_repr(result)
        result_output: dict[str, Any] = {"type": "result", "text": rendered}
        if truncated:
            result_output["truncated"] = True
        outputs.append(result_output)
    if error_output:
        outputs.append(error_output)

    plot_outputs, plot_warning = _capture_plots()
    outputs.extend(plot_outputs)
    warning_stream = _stream("stderr", plot_warning)
    if warning_stream:
        outputs.append(warning_stream)
    return {"ok": ok, "outputs": outputs}


def _reply(value: dict[str, Any], control_output: Any) -> None:
    payload = json.dumps(value, separators=(",", ":"))
    if len(payload) > MAX_CONTROL_REPLY_CHARACTERS:
        request_id = str(value.get("id", ""))
        payload = json.dumps({
            "id": request_id,
            "ok": False,
            "outputs": [{
                "type": "error",
                "name": "OutputLimitError",
                "message": "The kernel response exceeded its control-channel limit",
                "traceback": "",
            }],
        }, separators=(",", ":"))
    control_output.write(payload + "\n")
    control_output.flush()


def _control_streams() -> tuple[Any, Any]:
    """Detach protocol pipes from all file descriptors notebook code inherits."""
    sys.stdout.flush()
    sys.stderr.flush()
    input_fd = os.dup(sys.stdin.fileno())
    output_fd = os.dup(sys.stdout.fileno())
    os.set_inheritable(input_fd, False)
    os.set_inheritable(output_fd, False)
    control_input = os.fdopen(input_fd, "r", encoding="utf-8", errors="strict")
    control_output = os.fdopen(output_fd, "w", encoding="utf-8", errors="strict")

    null_flags = os.O_RDWR | getattr(os, "O_BINARY", 0)
    null_fd = os.open(os.devnull, null_flags)
    try:
        for descriptor in (0, 1, 2):
            os.dup2(null_fd, descriptor)
    finally:
        os.close(null_fd)
    return control_input, control_output


def serve() -> None:
    control_input, control_output = _control_streams()
    try:
        while True:
            raw_line = control_input.readline(MAX_CONTROL_REQUEST_CHARACTERS + 1)
            if not raw_line:
                break
            if len(raw_line) > MAX_CONTROL_REQUEST_CHARACTERS or not raw_line.endswith("\n"):
                _reply({
                    "id": "",
                    "ok": False,
                    "outputs": [{
                        "type": "error",
                        "name": "RequestLimitError",
                        "message": "The kernel request exceeded its control-channel limit",
                        "traceback": "",
                    }],
                }, control_output)
                break
            request: Any = None
            try:
                request = json.loads(raw_line)
                request_id = str(request.get("id", "")) if isinstance(request, dict) else ""
                source = request.get("source", "") if isinstance(request, dict) else None
                if not request_id or not isinstance(source, str):
                    raise ValueError("Kernel requests require an id and string source")
                _reply({"id": request_id, **_execute(source)}, control_output)
            except BaseException as error:
                request_id = ""
                if isinstance(request, dict):
                    request_id = str(request.get("id", ""))
                name = _type_name(error, limit=500, fallback="Exception")
                message, message_truncated = _safe_exception_message(error)
                trace, trace_truncated = _safe_traceback(error, name, message)
                output: dict[str, Any] = {
                    "type": "error",
                    "name": name,
                    "message": message,
                    "traceback": trace,
                }
                if message_truncated or trace_truncated:
                    output["truncated"] = True
                _reply({
                    "id": request_id,
                    "ok": False,
                    "outputs": [output],
                }, control_output)
    finally:
        control_input.close()
        control_output.close()


if __name__ == "__main__":
    serve()
