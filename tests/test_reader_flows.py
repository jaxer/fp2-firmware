"""Portable pure-flow checks with synthetic fixtures; never opens a live service."""

from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "components" / "fp2_poc"


class ReaderFlowTests(unittest.TestCase):
    def compile_run(self, name):
        with tempfile.TemporaryDirectory(prefix=f"fp2-{name}-") as temporary:
            executable = Path(temporary) / name
            subprocess.run(
                [
                    "c++",
                    "-std=c++17",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-fsanitize=address,undefined",
                    "-fno-omit-frame-pointer",
                    "-I",
                    str(COMPONENT),
                    str(ROOT / "tests" / f"{name}_harness.cpp"),
                    str(COMPONENT / f"{name}.cpp"),
                    "-o",
                    str(executable),
                ],
                check=True,
            )
            result = subprocess.run(
                [str(executable)], capture_output=True, text=True, check=False
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("checks passed", result.stdout)

    def test_configuration_reader(self):
        self.compile_run("configuration_reader")

    def test_native_snapshot(self):
        self.compile_run("native_snapshot")

    def test_learning(self):
        self.compile_run("learning")


if __name__ == "__main__":
    unittest.main()
