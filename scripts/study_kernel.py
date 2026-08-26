"""Persistent CPython execution bridge for the Lattice Study Lab.

The local library service owns this process and sends one JSON request per
line on stdin; every reply is one JSON line on stdout. User stdout/stderr are
captured so the protocol channel stays clean. This is a faithful port of
Lunaris's ``lunaris_kernel.py`` minus its WebAgg interactive-plot layer —
Study Lab serves PNG captures only.

Execution is trusted: cells run with full user permissions in a persistent
namespace. This is not a sandbox.
"""

from __future__ import annotations

import ast
import base64
import builtins
import contextlib
import io
import json
import os
import sys
import threading
import traceback
import warnings
from typing import Any

MAX_OUTPUT_CHARACTERS = 100_000
MAX_PLOTS = 8
MAX_PLOT_BYTES = 4_000_000

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


def _limited(value: str) -> tuple[str, bool]:
    if len(value) <= MAX_OUTPUT_CHARACTERS:
        return value, False
    return value[:MAX_OUTPUT_CHARACTERS], True


def _stream(name: str, value: str) -> dict[str, Any] | None:
    if not value:
        return None
    text, truncated = _limited(value)
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
            buffer = io.BytesIO()
            figure.savefig(buffer, format="png", bbox_inches="tight")
            data = buffer.getvalue()
            if len(data) > MAX_PLOT_BYTES:
                notes.append(
                    f"Plot {figure_number} was omitted because its PNG exceeded {MAX_PLOT_BYTES:,} bytes.\n"
                )
                continue
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
        return [], f"Lattice could not capture a plot: {error}\n"


def _execute(source: str) -> dict[str, Any]:
    stdout = io.StringIO()
    stderr = io.StringIO()
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
        trace = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        limited_trace, truncated = _limited(trace)
        error_output = {
            "type": "error",
            "name": type(error).__name__,
            "message": str(error),
            "traceback": limited_trace,
        }
        if truncated:
            error_output["truncated"] = True

    stdout_output = _stream("stdout", stdout.getvalue())
    stderr_output = _stream("stderr", stderr.getvalue())
    if stdout_output:
        outputs.append(stdout_output)
    if stderr_output:
        outputs.append(stderr_output)
    if ok and result is not None:
        rendered, truncated = _limited(repr(result))
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


def _reply(value: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(value, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def serve() -> None:
    for raw_line in sys.stdin:
        request: Any = None
        try:
            request = json.loads(raw_line)
            request_id = str(request.get("id", "")) if isinstance(request, dict) else ""
            source = request.get("source", "") if isinstance(request, dict) else None
            if not request_id or not isinstance(source, str):
                raise ValueError("Kernel requests require an id and string source")
            _reply({"id": request_id, **_execute(source)})
        except BaseException as error:
            request_id = ""
            if isinstance(request, dict):
                request_id = str(request.get("id", ""))
            _reply({
                "id": request_id,
                "ok": False,
                "outputs": [{
                    "type": "error",
                    "name": type(error).__name__,
                    "message": str(error),
                    "traceback": "".join(traceback.format_exception_only(type(error), error)),
                }],
            })


if __name__ == "__main__":
    serve()
