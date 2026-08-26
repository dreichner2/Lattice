from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "windows"))

import server_bootstrap  # noqa: E402
import study_kernel  # noqa: E402
import study_python  # noqa: E402


class KernelBridgeTests(unittest.TestCase):
    """Exercise the bridge's _execute directly (in-process, no subprocess)."""

    def tearDown(self) -> None:
        study_kernel.NAMESPACE.clear()
        study_kernel.NAMESPACE.update({
            "__name__": "__main__",
            "__builtins__": study_kernel.builtins,
        })

    def exec_source(self, source: str) -> dict:
        return study_kernel._execute(source)

    def test_plain_exec_captures_stdout(self) -> None:
        result = self.exec_source("print('hello')")
        self.assertTrue(result["ok"])
        self.assertEqual(result["outputs"][0]["type"], "stream")
        self.assertEqual(result["outputs"][0]["name"], "stdout")
        self.assertIn("hello", result["outputs"][0]["text"])

    def test_trailing_expression_becomes_result_and_sets_underscore(self) -> None:
        result = self.exec_source("x = 21\nx * 2")
        self.assertTrue(result["ok"])
        kinds = [output["type"] for output in result["outputs"]]
        self.assertIn("result", kinds)
        result_output = next(o for o in result["outputs"] if o["type"] == "result")
        self.assertEqual(result_output["text"], "42")
        self.assertEqual(study_kernel.NAMESPACE.get("_"), 42)

    def test_exception_keeps_kernel_alive_and_reports(self) -> None:
        result = self.exec_source("raise ValueError('boom')")
        self.assertFalse(result["ok"])
        error = next(o for o in result["outputs"] if o["type"] == "error")
        self.assertEqual(error["name"], "ValueError")
        self.assertEqual(error["message"], "boom")
        self.assertIn("ValueError", error["traceback"])

    def test_namespace_persists_across_calls(self) -> None:
        self.exec_source("counter = 1")
        result = self.exec_source("counter += 1\ncounter")
        result_output = next(o for o in result["outputs"] if o["type"] == "result")
        self.assertEqual(result_output["text"], "2")

    def test_input_is_blocked(self) -> None:
        result = self.exec_source("input()")
        self.assertFalse(result["ok"])
        error = next(o for o in result["outputs"] if o["type"] == "error")
        self.assertIn("input()", error["message"])

    def test_output_truncation(self) -> None:
        result = self.exec_source("print('a' * 200_000)")
        stdout = next(o for o in result["outputs"] if o["type"] == "stream")
        self.assertLessEqual(len(stdout["text"]), study_kernel.MAX_OUTPUT_CHARACTERS)
        self.assertTrue(stdout.get("truncated"))

    def test_stream_capture_discards_overflow_while_writing(self) -> None:
        buffer = study_kernel._BoundedTextBuffer(32)
        self.assertEqual(buffer.write("x" * 1_000_000), 1_000_000)
        self.assertEqual(buffer.getvalue(), "x" * 32)
        self.assertTrue(buffer.truncated)

    def test_stream_capture_bypasses_polymorphic_string_slicing(self) -> None:
        class ExpandingString(str):
            def __len__(self) -> int:
                return 5_000_000

            def __getitem__(self, key: object) -> str:
                return "x" * 5_000_000

        buffer = study_kernel._BoundedTextBuffer(32)
        self.assertEqual(buffer.write(ExpandingString("safe")), 4)
        self.assertEqual(buffer.getvalue(), "safe")
        self.assertFalse(buffer.truncated)

    def test_exception_message_and_traceback_are_bounded(self) -> None:
        result = self.exec_source("raise ValueError('x' * 200_000)")
        error = next(o for o in result["outputs"] if o["type"] == "error")
        self.assertLessEqual(len(error["message"]), study_kernel.MAX_OUTPUT_CHARACTERS)
        self.assertLessEqual(len(error["traceback"]), study_kernel.MAX_OUTPUT_CHARACTERS)
        self.assertTrue(error.get("truncated"))

    def test_string_subclass_cannot_expand_during_exception_truncation(self) -> None:
        result = self.exec_source(
            "class ExpandingString(str):\n"
            "    def __getitem__(self, key):\n"
            "        return 'x' * 5_000_000\n"
            "raise ValueError(ExpandingString('boom'))"
        )
        error = next(o for o in result["outputs"] if o["type"] == "error")
        self.assertLessEqual(len(error["message"]), study_kernel.MAX_OUTPUT_CHARACTERS)
        self.assertLessEqual(len(error["traceback"]), study_kernel.MAX_OUTPUT_CHARACTERS)

    def test_large_range_uses_bounded_integer_rendering(self) -> None:
        result = self.exec_source("range(1 << 2_000_000)")
        output = next(o for o in result["outputs"] if o["type"] == "result")
        self.assertLessEqual(len(output["text"]), study_kernel.MAX_OUTPUT_CHARACTERS)
        self.assertIn("bits", output["text"])
        self.assertTrue(output.get("truncated"))

    def test_result_does_not_invoke_unbounded_custom_repr(self) -> None:
        result = self.exec_source(
            "class HugeRepresentation:\n"
            "    def __repr__(self):\n"
            "        return 'x' * 5_000_000\n"
            "HugeRepresentation()"
        )
        output = next(o for o in result["outputs"] if o["type"] == "result")
        self.assertIn("HugeRepresentation", output["text"])
        self.assertLessEqual(len(output["text"]), study_kernel.MAX_OUTPUT_CHARACTERS)

    def test_result_label_bypasses_metaclass_data_descriptors(self) -> None:
        descriptor_calls: list[bool] = []

        class DescriptorMeta(type):
            pass

        DescriptorMeta.__module__ = property(  # type: ignore[assignment]
            lambda cls: descriptor_calls.append(True) or "x" * 5_000_000
        )

        class DescriptorValue(metaclass=DescriptorMeta):
            pass

        rendered, _ = study_kernel._safe_repr(DescriptorValue())
        self.assertIn("DescriptorValue", rendered)
        self.assertEqual(descriptor_calls, [])
        self.assertLessEqual(len(rendered), study_kernel.MAX_OUTPUT_CHARACTERS)

    def test_matplotlib_plots_captured_as_png_when_available(self) -> None:
        try:
            import matplotlib  # noqa: F401
        except ImportError:
            self.skipTest("matplotlib is not installed")
        source = (
            "import matplotlib.pyplot as plt\n"
            "plt.figure()\n"
            "plt.plot([1, 2, 3], [1, 4, 9])\n"
        )
        result = self.exec_source(source)
        self.assertTrue(result["ok"])
        images = [o for o in result["outputs"] if o["type"] == "image"]
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0]["mime"], "image/png")


class SupervisorTests(unittest.TestCase):
    """Drive the real bridge process through StudyPythonRuntime."""

    def setUp(self) -> None:
        self.runtime = study_python.StudyPythonRuntime(python_command=[sys.executable])

    def tearDown(self) -> None:
        self.runtime.stop_all()

    def descendant_source(self, ready: Path, marker: Path) -> str:
        grandchild = (
            "import pathlib, time; "
            "time.sleep(0.6); "
            f"pathlib.Path({str(marker)!r}).write_text('survived')"
        )
        child = (
            "import pathlib, subprocess, sys, time; "
            f"subprocess.Popen([sys.executable, '-c', {grandchild!r}]); "
            f"pathlib.Path({str(ready)!r}).write_text('ready'); "
            "time.sleep(30)"
        )
        return (
            "import pathlib, subprocess, sys, time\n"
            f"subprocess.Popen([sys.executable, '-c', {child!r}])\n"
            f"ready = pathlib.Path({str(ready)!r})\n"
            "deadline = time.monotonic() + 5\n"
            "while not ready.exists() and time.monotonic() < deadline:\n"
            "    time.sleep(0.01)\n"
            "ready.exists()"
        )

    def test_status_shape(self) -> None:
        status = self.runtime.status()
        self.assertTrue(status["available"])
        self.assertEqual(status["maxKernels"], study_python.MAX_KERNELS)

    def test_launch_command_supports_source_and_frozen_services(self) -> None:
        self.assertEqual(
            study_python._kernel_launch_command(["python"], frozen=False),
            ["python", "-X", "utf8", "-u", str(study_python.KERNEL_SCRIPT)],
        )
        self.assertEqual(
            study_python._kernel_launch_command(["LatticeServer.exe"], frozen=True),
            ["LatticeServer.exe", "--study-kernel"],
        )

    def test_windows_bootstrap_has_an_exact_kernel_mode(self) -> None:
        with mock.patch.object(study_kernel, "serve") as serve:
            self.assertEqual(server_bootstrap.bootstrap(["--study-kernel"]), 0)
        serve.assert_called_once_with()

    def test_kernel_does_not_inherit_private_study_capability(self) -> None:
        with mock.patch.dict(os.environ, {"LATTICE_PRIVATE_TOKEN": "private-value"}):
            result = self.runtime.run(
                "nb-private-env",
                "import os\nos.environ.get('LATTICE_PRIVATE_TOKEN') is None",
            )
        value = next(o for o in result["outputs"] if o["type"] == "result")
        self.assertEqual(value["text"], "True")

    def test_busy_kernel_is_never_selected_for_idle_eviction(self) -> None:
        class BusyKernel:
            alive = True
            busy = True
            last_used = 0.0

            def stop(self, _reason: str) -> None:
                raise AssertionError("busy kernel must not be stopped")

        original = study_python.MAX_KERNELS
        study_python.MAX_KERNELS = 1
        self.runtime._kernels["busy"] = BusyKernel()  # type: ignore[assignment]
        try:
            with self.assertRaises(study_python.KernelUnavailable):
                self.runtime.run("new", "1 + 1")
        finally:
            self.runtime._kernels.clear()
            study_python.MAX_KERNELS = original

    def test_run_returns_outputs_from_real_process(self) -> None:
        result = self.runtime.run("nb-1", "print('via stdio')\n6 * 7")
        self.assertTrue(result["ok"])
        stream = next(o for o in result["outputs"] if o["type"] == "stream")
        self.assertIn("via stdio", stream["text"])
        value = next(o for o in result["outputs"] if o["type"] == "result")
        self.assertEqual(value["text"], "42")

    def test_state_persists_within_notebook_kernel(self) -> None:
        self.runtime.run("nb-2", "secret = 'lattice'")
        result = self.runtime.run("nb-2", "secret.upper()")
        value = next(o for o in result["outputs"] if o["type"] == "result")
        self.assertEqual(value["text"], "'LATTICE'")

    def test_restart_clears_state(self) -> None:
        self.runtime.run("nb-3", "token = 5")
        self.runtime.restart("nb-3")
        result = self.runtime.run("nb-3", "token")
        self.assertFalse(result["ok"])
        error = next(o for o in result["outputs"] if o["type"] == "error")
        self.assertEqual(error["name"], "NameError")

    def test_restart_invalidates_and_interrupts_an_inflight_result(self) -> None:
        errors: list[BaseException] = []

        def run_cell() -> None:
            try:
                self.runtime.run("nb-restart-race", "import time\ntime.sleep(30)\n42")
            except BaseException as exc:
                errors.append(exc)

        runner = threading.Thread(target=run_cell)
        runner.start()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            kernel = self.runtime._kernels.get("nb-restart-race")
            if kernel is not None and kernel.busy:
                break
            time.sleep(0.01)
        else:
            self.fail("the kernel did not begin the controlled run")
        self.runtime.restart("nb-restart-race")
        runner.join(timeout=5)
        self.assertFalse(runner.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], study_python.KernelUnavailable)
        recovered = self.runtime.run("nb-restart-race", "40 + 2")
        value = next(o for o in recovered["outputs"] if o["type"] == "result")
        self.assertEqual(value["text"], "42")

    def test_separate_kernels_are_isolated(self) -> None:
        self.runtime.run("nb-a", "only_a = 'A'")
        result = self.runtime.run("nb-b", "'only_a' in dir()")
        value = next(o for o in result["outputs"] if o["type"] == "result")
        self.assertEqual(value["text"], "False")

    def test_error_output_does_not_kill_process(self) -> None:
        failed = self.runtime.run("nb-4", "1 / 0")
        self.assertFalse(failed["ok"])
        error = next(o for o in failed["outputs"] if o["type"] == "error")
        self.assertEqual(error["name"], "ZeroDivisionError")
        recovered = self.runtime.run("nb-4", "2 + 3")
        self.assertTrue(recovered["ok"])

    def test_real_bridge_bounds_polymorphic_exception_messages(self) -> None:
        failed = self.runtime.run(
            "nb-polymorphic-output",
            "class ExpandingString(str):\n"
            "    def __getitem__(self, key):\n"
            "        return 'x' * 5_000_000\n"
            "raise ValueError(ExpandingString('boom'))",
        )
        error = next(o for o in failed["outputs"] if o["type"] == "error")
        self.assertLessEqual(len(error["message"]), study_kernel.MAX_OUTPUT_CHARACTERS)
        self.assertLessEqual(len(error["traceback"]), study_kernel.MAX_OUTPUT_CHARACTERS)

    def test_real_bridge_bounds_polymorphic_stream_writes(self) -> None:
        result = self.runtime.run(
            "nb-polymorphic-stream",
            "class ExpandingString(str):\n"
            "    def __len__(self):\n"
            "        return 5_000_000\n"
            "    def __getitem__(self, key):\n"
            "        return 'x' * 5_000_000\n"
            "import sys\n"
            "sys.stdout.write(ExpandingString('safe'))",
        )
        stream = next(o for o in result["outputs"] if o["type"] == "stream")
        self.assertEqual(stream["text"], "safe")

    def test_real_bridge_bypasses_metaclass_label_descriptors(self) -> None:
        result = self.runtime.run(
            "nb-metaclass-label",
            "class DescriptorMeta(type):\n"
            "    pass\n"
            "DescriptorMeta.__module__ = property(lambda cls: "
            "(_ for _ in ()).throw(RuntimeError('descriptor ran')))\n"
            "class DescriptorValue(metaclass=DescriptorMeta):\n"
            "    pass\n"
            "DescriptorValue()",
        )
        self.assertTrue(result["ok"])
        output = next(o for o in result["outputs"] if o["type"] == "result")
        self.assertIn("DescriptorValue", output["text"])

    def test_timeout_stops_runaway_cell(self) -> None:
        original = study_python.EXECUTE_TIMEOUT_SECONDS
        study_python.EXECUTE_TIMEOUT_SECONDS = 2.0
        try:
            with self.assertRaises(study_python.KernelError):
                self.runtime.run("nb-5", "while True:\n    pass")
        finally:
            study_python.EXECUTE_TIMEOUT_SECONDS = original
        # The kernel was stopped; a fresh one must start cleanly.
        recovered = self.runtime.run("nb-5", "40 + 2")
        self.assertTrue(recovered["ok"])

    def test_timeout_terminates_descendant_process_tree_promptly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / "descendant-survived.txt"
            child_source = (
                "import pathlib, time; "
                "time.sleep(0.8); "
                f"pathlib.Path({str(marker)!r}).write_text('survived')"
            )
            source = (
                "import subprocess, sys, time\n"
                f"subprocess.Popen([sys.executable, '-c', {child_source!r}])\n"
                "time.sleep(30)"
            )
            original = study_python.EXECUTE_TIMEOUT_SECONDS
            study_python.EXECUTE_TIMEOUT_SECONDS = 0.2
            started = time.monotonic()
            try:
                with self.assertRaises(study_python.KernelError):
                    self.runtime.run("nb-process-tree", source)
            finally:
                study_python.EXECUTE_TIMEOUT_SECONDS = original
            self.assertLess(time.monotonic() - started, 1.5)
            time.sleep(0.9)
            self.assertFalse(marker.exists())

    def test_restart_eviction_and_shutdown_terminate_grandchildren(self) -> None:
        for action in ("restart", "evict", "shutdown"):
            with self.subTest(action=action), tempfile.TemporaryDirectory() as temporary:
                runtime = study_python.StudyPythonRuntime(python_command=[sys.executable])
                ready = Path(temporary) / "descendant-ready.txt"
                marker = Path(temporary) / "grandchild-survived.txt"
                original = study_python.MAX_KERNELS
                try:
                    result = runtime.run("owned", self.descendant_source(ready, marker))
                    value = next(o for o in result["outputs"] if o["type"] == "result")
                    self.assertEqual(value["text"], "True")
                    if action == "restart":
                        runtime.restart("owned")
                    elif action == "evict":
                        study_python.MAX_KERNELS = 1
                        runtime.run("replacement", "40 + 2")
                    else:
                        runtime.stop_all()
                    time.sleep(0.7)
                    self.assertFalse(marker.exists())
                finally:
                    study_python.MAX_KERNELS = original
                    runtime.stop_all()

    def test_notebook_code_cannot_write_a_forged_reply_to_standard_output(self) -> None:
        source = (
            "import inspect, json, os, time\n"
            "frame = inspect.currentframe()\n"
            "request = ''\n"
            "while frame is not None:\n"
            "    candidate = frame.f_locals.get('request_id')\n"
            "    if candidate:\n"
            "        request = candidate\n"
            "        break\n"
            "    frame = frame.f_back\n"
            "os.write(1, (json.dumps({'id': request, 'ok': True, "
            "'outputs': [{'type': 'result', 'text': 'forged'}]}) + '\\n').encode())\n"
            "time.sleep(0.25)\n"
            "42"
        )
        started = time.monotonic()
        result = self.runtime.run("nb-control-channel", source)
        self.assertGreaterEqual(time.monotonic() - started, 0.2)
        output = next(o for o in result["outputs"] if o["type"] == "result")
        self.assertEqual(output["text"], "42")

    def test_runtime_cannot_admit_a_kernel_after_shutdown(self) -> None:
        self.runtime.stop_all()
        self.assertFalse(self.runtime.status()["available"])
        with self.assertRaises(study_python.KernelUnavailable):
            self.runtime.run("after-close", "40 + 2")

    def test_shutdown_invalidates_and_interrupts_an_inflight_result(self) -> None:
        errors: list[BaseException] = []

        def run_cell() -> None:
            try:
                self.runtime.run("nb-close-race", "import time\ntime.sleep(30)\n42")
            except BaseException as exc:
                errors.append(exc)

        runner = threading.Thread(target=run_cell)
        runner.start()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            kernel = self.runtime._kernels.get("nb-close-race")
            if kernel is not None and kernel.busy:
                break
            time.sleep(0.01)
        else:
            self.fail("the kernel did not begin the controlled run")
        self.runtime.stop_all()
        runner.join(timeout=5)
        self.assertFalse(runner.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], study_python.KernelUnavailable)
        self.assertEqual(self.runtime._kernels, {})

    def test_shutdown_waits_for_concurrent_restart_teardown(self) -> None:
        self.runtime.run("nb-stop-join", "ready = True")
        kernel = self.runtime._kernels["nb-stop-join"]
        teardown_entered = threading.Event()
        allow_teardown = threading.Event()
        restart_errors: list[BaseException] = []
        shutdown_errors: list[BaseException] = []
        original_terminate = kernel._terminate_process_tree

        def blocked_terminate() -> None:
            teardown_entered.set()
            if not allow_teardown.wait(timeout=5):
                raise AssertionError("controlled kernel teardown was never released")
            original_terminate()

        def restart_kernel() -> None:
            try:
                self.runtime.restart("nb-stop-join")
            except BaseException as exc:
                restart_errors.append(exc)

        def shutdown_runtime() -> None:
            try:
                self.runtime.stop_all()
            except BaseException as exc:
                shutdown_errors.append(exc)

        with mock.patch.object(
            kernel,
            "_terminate_process_tree",
            side_effect=blocked_terminate,
        ):
            restart = threading.Thread(target=restart_kernel)
            restart.start()
            self.assertTrue(teardown_entered.wait(timeout=5))

            shutdown = threading.Thread(target=shutdown_runtime)
            shutdown.start()
            time.sleep(0.1)
            self.assertTrue(
                shutdown.is_alive(),
                "shutdown returned before the concurrent kernel stop completed",
            )

            allow_teardown.set()
            restart.join(timeout=5)
            shutdown.join(timeout=5)

        self.assertFalse(restart.is_alive())
        self.assertFalse(shutdown.is_alive())
        self.assertEqual(restart_errors, [])
        self.assertEqual(shutdown_errors, [])
        self.assertFalse(kernel.alive)
        self.assertTrue(kernel._stop_complete.is_set())
        self.assertFalse(self.runtime.status()["available"])
        self.assertEqual(self.runtime._kernels, {})
        self.assertEqual(self.runtime._stopping_kernels, set())

    def test_protocol_rejects_malformed_requests(self) -> None:
        # Feed a malformed line straight into a kernel process via run():
        # valid JSON but missing fields -> the bridge replies with an error.
        runtime = self.runtime
        runtime.run("nb-6", "ready = True")
        kernel = runtime._kernels["nb-6"]
        self.assertTrue(kernel.alive)


if __name__ == "__main__":
    unittest.main()
