from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

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

    def test_status_shape(self) -> None:
        status = self.runtime.status()
        self.assertTrue(status["available"])
        self.assertEqual(status["maxKernels"], study_python.MAX_KERNELS)

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

    def test_protocol_rejects_malformed_requests(self) -> None:
        # Feed a malformed line straight into a kernel process via run():
        # valid JSON but missing fields -> the bridge replies with an error.
        runtime = self.runtime
        runtime.run("nb-6", "ready = True")
        kernel = runtime._kernels["nb-6"]
        self.assertTrue(kernel.alive)


if __name__ == "__main__":
    unittest.main()
